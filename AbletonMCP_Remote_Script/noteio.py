# Copyright (C) 2026 Yoka
# SPDX-License-Identifier: AGPL-3.0-only
"""Reading and writing MIDI notes, independent of where the clip lives.

One note format is used on the wire in both directions::

    {"pitch": 60, "start_time": 0.0, "duration": 0.25, "velocity": 100, "mute": false}

Times are in beats. Input is lenient about key names (see `_ALIASES`).
The Live 11+ note API is used; the pre-11 calls serve as fallback.
"""

from .errors import BAD_PARAMS, UNSUPPORTED, CommandError
from .liveaccess import peek

_ALIASES = {
    "start_time": ("start_time", "start", "time", "position"),
    "duration": ("duration", "dur", "length"),
    "velocity": ("velocity", "vel"),
    "mute": ("mute", "muted"),
}
_SHORTEST = 1.0 / 256.0
_EXTRA_DEFAULTS = (("probability", 1.0), ("velocity_deviation", 0.0),
                   ("release_velocity", 64.0))


def _first(note, field, fallback):
    for key in _ALIASES[field]:
        if key in note and note[key] is not None:
            return note[key]
    return fallback


def normalise(notes):
    """Validate client notes and bring them into the wire format."""
    cleaned = []
    for position, note in enumerate(notes):
        if not isinstance(note, dict):
            raise CommandError(BAD_PARAMS, "note %d is not an object" % position)
        try:
            pitch = int(note.get("pitch", 60))
            start = float(_first(note, "start_time", 0.0))
            duration = float(_first(note, "duration", 0.25))
            velocity = int(round(float(_first(note, "velocity", 100))))
        except (TypeError, ValueError):
            raise CommandError(BAD_PARAMS, "note %d has a non-numeric field" % position)
        if not 0 <= pitch <= 127:
            raise CommandError(BAD_PARAMS, "note %d: pitch %d is outside 0..127" % (position, pitch))
        mute = _first(note, "mute", False)
        if isinstance(mute, str):
            mute = mute.strip().lower() in ("true", "1", "yes")
        entry = {
            "pitch": pitch,
            "start_time": start,
            "duration": max(duration, _SHORTEST),
            "velocity": max(1, min(127, velocity)),
            "mute": bool(mute),
        }
        for extra in ("probability", "velocity_deviation", "release_velocity"):
            if note.get(extra) is not None:
                entry[extra] = float(note[extra])
        cleaned.append(entry)
    return cleaned


def whole_span(clip):
    """(start, length) in beats covering every note the clip can hold."""
    starts = [0.0]
    ends = [float(peek(clip, "length", 0.0) or 0.0)]
    for name in ("start_marker", "loop_start"):
        value = peek(clip, name)
        if value is not None:
            starts.append(float(value))
    for name in ("end_marker", "loop_end"):
        value = peek(clip, name)
        if value is not None:
            ends.append(float(value))
    start = min(starts)
    return start, max(max(ends) - start, _SHORTEST)


def read(clip, pitch=None, start=None, span=None):
    """Notes of a clip as wire dicts, ordered by time then pitch."""
    whole_start, whole_length = whole_span(clip)
    from_time = whole_start if start is None else start
    time_span = whole_length if span is None else span
    from_pitch, pitch_span = (0, 128) if pitch is None else (pitch, 1)
    reader = peek(clip, "get_notes_extended")
    notes = []
    if reader is not None:
        for raw in reader(from_pitch, pitch_span, from_time, time_span):
            note = {
                "pitch": int(raw.pitch),
                "start_time": round(float(raw.start_time), 6),
                "duration": round(float(raw.duration), 6),
                "velocity": int(round(raw.velocity)),
                "mute": bool(raw.mute),
            }
            # Carried only when they differ from Live's defaults.
            for extra, default in _EXTRA_DEFAULTS:
                value = peek(raw, extra)
                if value is not None and abs(float(value) - default) > 1e-6:
                    note[extra] = round(float(value), 6)
            notes.append(note)
    else:
        legacy = peek(clip, "get_notes")
        if legacy is None:
            raise CommandError(UNSUPPORTED, "this clip does not offer note access")
        for raw in legacy(from_time, from_pitch, time_span, pitch_span):
            notes.append({
                "pitch": int(raw[0]),
                "start_time": round(float(raw[1]), 6),
                "duration": round(float(raw[2]), 6),
                "velocity": int(raw[3]),
                "mute": bool(raw[4]) if len(raw) > 4 else False,
            })
    notes.sort(key=lambda n: (n["start_time"], n["pitch"]))
    return notes


def erase(clip, pitch=None, start=None, span=None):
    """Remove notes; without arguments the clip is emptied."""
    whole_start, whole_length = whole_span(clip)
    from_time = whole_start if start is None else start
    time_span = whole_length if span is None else span
    from_pitch, pitch_span = (0, 128) if pitch is None else (pitch, 1)
    remover = peek(clip, "remove_notes_extended")
    if remover is not None:
        remover(from_pitch, pitch_span, from_time, time_span)
        return
    legacy = peek(clip, "remove_notes")
    if legacy is None:
        raise CommandError(UNSUPPORTED, "this clip does not offer note removal")
    legacy(from_time, from_pitch, time_span, pitch_span)


def add(clip, notes, live_module):
    """Add already normalised notes to a clip in one call."""
    if not notes:
        return 0
    adder = peek(clip, "add_new_notes")
    if adder is not None:
        make = live_module.Clip.MidiNoteSpecification
        specs = []
        for note in notes:
            fields = dict(
                pitch=note["pitch"],
                start_time=note["start_time"],
                duration=note["duration"],
                velocity=float(note["velocity"]),
                mute=note["mute"],
            )
            for extra in ("probability", "velocity_deviation", "release_velocity"):
                if extra in note:
                    fields[extra] = note[extra]
            specs.append(make(**fields))
        adder(tuple(specs))
        return len(specs)
    legacy = peek(clip, "set_notes")
    if legacy is None:
        raise CommandError(UNSUPPORTED, "this clip does not offer note writing")
    legacy(tuple(
        (n["pitch"], n["start_time"], n["duration"], n["velocity"], n["mute"]) for n in notes
    ))
    return len(notes)


def replace_all(clip, notes, live_module):
    """Empty the clip, then write ``notes``. One undo step in Live."""
    erase(clip)
    return add(clip, notes, live_module)
