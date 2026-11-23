# Copyright (C) 2026 Yoka
# SPDX-License-Identifier: AGPL-3.0-only
"""Session clips and their MIDI notes."""

import random

from .. import noteio
from ..errors import BAD_PARAMS, BUSY, WRONG_KIND, CommandError
from ..liveaccess import peek
from ..registry import READ, REVERSIBLE, Bool, Float, Int, Items, Text, command


@command("create_clip", zone=REVERSIBLE,
         summary="Create an empty MIDI clip in a Session slot",
         params=[Int("track_index"), Int("clip_index"), Float("length", 4.0)])
def create_clip(live, track_index, clip_index, length):
    if length <= 0:
        raise CommandError(BAD_PARAMS, "length must be positive")
    track = live.track(track_index)
    if not peek(track, "has_midi_input", False):
        raise CommandError(WRONG_KIND, "'%s' is not a MIDI track" % track.name)
    slot = live.slot(track_index, clip_index)
    if slot.has_clip:
        raise CommandError(BUSY, "slot %d on '%s' already holds '%s'"
                           % (clip_index, track.name, slot.clip.name))
    slot.create_clip(length)

    def valid():
        try:
            return None if slot.has_clip else "the clip is no longer there"
        except Exception:
            return "the slot no longer exists"

    def undo():
        slot.delete_clip()
        return {"deleted_clip": True}

    live.record("Created a %g-beat clip on '%s', slot %d" % (length, track.name, clip_index),
                undo, valid)
    return {"track_index": track_index, "clip_index": clip_index,
            "name": slot.clip.name, "length": slot.clip.length}


@command("set_clip_name", zone=REVERSIBLE, summary="Rename a Session clip",
         params=[Int("track_index"), Int("clip_index"), Text("name")])
def set_clip_name(live, track_index, clip_index, name):
    clip = live.session_clip(track_index, clip_index)
    before = clip.name
    clip.name = name
    live.record_value("Clip name: '%s' -> '%s'" % (before, clip.name), clip, "name", before)
    return {"track_index": track_index, "clip_index": clip_index, "name": clip.name}


@command("fire_clip", zone=REVERSIBLE, undo="none", journal=False,
         summary="Launch a Session clip",
         params=[Int("track_index"), Int("clip_index")])
def fire_clip(live, track_index, clip_index):
    clip = live.session_clip(track_index, clip_index)
    live.slot(track_index, clip_index).fire()
    return {"track_index": track_index, "clip_index": clip_index, "name": clip.name}


@command("stop_clip", zone=REVERSIBLE, undo="none", journal=False,
         summary="Stop the clip playing in this slot's track",
         params=[Int("track_index"), Int("clip_index")])
def stop_clip(live, track_index, clip_index):
    slot = live.slot(track_index, clip_index)
    slot.stop()
    return {"track_index": track_index, "clip_index": clip_index, "had_clip": bool(slot.has_clip)}


@command("add_notes_to_clip", zone=REVERSIBLE,
         summary="Add notes to a Session MIDI clip (existing notes stay)",
         params=[Int("track_index"), Int("clip_index"), Items("notes")])
def add_notes_to_clip(live, track_index, clip_index, notes):
    clip = live.session_clip(track_index, clip_index, kind="midi")
    cleaned = noteio.normalise(notes)
    before = noteio.read(clip)
    written = noteio.add(clip, cleaned, live.live_module())
    record_notes(live, clip, before, "Added %d notes to '%s'" % (written, clip.name))
    return {"added": written, "clip": clip.name}


@command("replace_notes_in_clip", zone=REVERSIBLE,
         summary="Replace all notes of a Session MIDI clip in one step",
         params=[Int("track_index"), Int("clip_index"), Items("notes")])
def replace_notes_in_clip(live, track_index, clip_index, notes):
    clip = live.session_clip(track_index, clip_index, kind="midi")
    cleaned = noteio.normalise(notes)  # validate before anything is erased
    before = noteio.read(clip)
    written = noteio.replace_all(clip, cleaned, live.live_module())
    record_notes(live, clip, before, "Replaced the notes of '%s': %d -> %d notes"
                 % (clip.name, len(before), written))
    return {"written": written, "removed": len(before), "clip": clip.name}


@command("delete_notes_from_clip", zone=REVERSIBLE,
         summary="Delete notes, optionally only one pitch and/or a time range",
         params=[Int("track_index"), Int("clip_index"), Int("pitch", None),
                 Float("start_time", None), Float("time_span", None)])
def delete_notes_from_clip(live, track_index, clip_index, pitch, start_time, time_span):
    clip = live.session_clip(track_index, clip_index, kind="midi")
    if pitch is not None and not 0 <= pitch <= 127:
        raise CommandError(BAD_PARAMS, "pitch must be within 0..127")
    before = noteio.read(clip)
    span = time_span
    if start_time is not None and time_span is None:
        whole_start, whole_length = noteio.whole_span(clip)
        span = max(whole_start + whole_length - start_time, 0.0)
    noteio.erase(clip, pitch=pitch, start=start_time, span=span)
    after = len(noteio.read(clip))
    record_notes(live, clip, before, "Deleted %d notes from '%s'"
                 % (len(before) - after, clip.name))
    return {"deleted": len(before) - after, "remaining": after, "clip": clip.name,
            "pitch": pitch, "start_time": start_time, "time_span": span}


def record_notes(live, clip, before, text):
    """Journal a note edit; undo writes the previous notes back."""
    after = noteio.read(clip)
    module = live.live_module()

    def valid():
        try:
            current = noteio.read(clip)
        except Exception:
            return "the clip no longer exists"
        return None if current == after else "the notes were changed since"

    def undo():
        noteio.replace_all(clip, before, module)
        return {"restored_notes": len(before)}

    live.record(text, undo, valid)


def _clip_notes_reply(clip, track_index, clip_index):
    notes = noteio.read(clip)
    return {
        "track_index": track_index,
        "clip_index": clip_index,
        "clip_name": clip.name,
        "length": clip.length,
        "note_count": len(notes),
        "notes": notes,
    }


@command("get_clip_notes", zone=READ, summary="All notes of a Session MIDI clip",
         params=[Int("track_index"), Int("clip_index")])
def get_clip_notes(live, track_index, clip_index):
    clip = live.session_clip(track_index, clip_index, kind="midi")
    return _clip_notes_reply(clip, track_index, clip_index)


@command("get_midi_clip_notes", zone=READ,
         summary="All notes of a Session MIDI clip (older name, slot_index parameter)",
         params=[Int("track_index"), Int("slot_index")])
def get_midi_clip_notes(live, track_index, slot_index):
    clip = live.session_clip(track_index, slot_index, kind="midi")
    return _clip_notes_reply(clip, track_index, slot_index)


@command("humanize_clip", zone=REVERSIBLE,
         summary="Randomly shift note starts (beats) and velocities of a MIDI clip",
         params=[Int("track_index"), Int("clip_index"), Float("timing_amount", 0.02),
                 Int("velocity_amount", 10), Int("seed", None)])
def humanize_clip(live, track_index, clip_index, timing_amount, velocity_amount, seed):
    if timing_amount < 0 or velocity_amount < 0:
        raise CommandError(BAD_PARAMS, "amounts must not be negative")
    clip = live.session_clip(track_index, clip_index, kind="midi")
    dice = random.Random(seed)
    before = noteio.read(clip)
    notes = [dict(note) for note in before]
    for note in notes:
        note["start_time"] = max(0.0, note["start_time"] + dice.uniform(-timing_amount, timing_amount))
        shifted = note["velocity"] + dice.randint(-velocity_amount, velocity_amount)
        note["velocity"] = max(1, min(127, shifted))
    noteio.replace_all(clip, notes, live.live_module())
    record_notes(live, clip, before, "Humanized %d notes in '%s'" % (len(notes), clip.name))
    return {"note_count": len(notes), "clip": clip.name,
            "timing_amount": timing_amount, "velocity_amount": velocity_amount}


@command("transpose_notes", zone=REVERSIBLE,
         summary="Shift all notes of a MIDI clip by semitones",
         params=[Int("track_index"), Int("clip_index"), Int("semitones")])
def transpose_notes(live, track_index, clip_index, semitones):
    clip = live.session_clip(track_index, clip_index, kind="midi")
    before = noteio.read(clip)
    out_of_range = [n for n in before if not 0 <= n["pitch"] + semitones <= 127]
    if out_of_range:
        raise CommandError(
            BAD_PARAMS,
            "%d note(s) would leave the MIDI range 0..127; nothing changed" % len(out_of_range),
        )
    notes = [dict(note, pitch=note["pitch"] + semitones) for note in before]
    noteio.replace_all(clip, notes, live.live_module())
    record_notes(live, clip, before, "Transposed '%s' by %+d semitones" % (clip.name, semitones))
    return {"semitones": semitones, "note_count": len(notes), "clip": clip.name}


@command("get_clip_audio_info", zone=READ,
         summary="File path, gain and warp state of an audio clip",
         params=[Int("track_index"), Int("clip_index"), Bool("arrangement", False)])
def get_clip_audio_info(live, track_index, clip_index, arrangement):
    clip = live.any_clip(track_index, clip_index, arrangement, kind="audio")
    return {
        "clip_name": clip.name,
        "file_path": peek(clip, "file_path"),
        "gain": clip.gain,
        "gain_display": peek(clip, "gain_display_string"),
        "warping": bool(peek(clip, "warping", False)),
        "length": clip.length,
    }


@command("normalize_clip", zone=REVERSIBLE,
         summary="Set an audio clip's gain so that its peak lands on target_db",
         params=[Int("track_index"), Int("clip_index"), Bool("arrangement", False),
                 Float("target_db", 0.0), Float("peak_db", None)])
def normalize_clip(live, track_index, clip_index, arrangement, target_db, peak_db):
    """``peak_db`` is the sample peak of the clip's file, measured by the
    caller (Live does not publish it). Without it the clip gain itself is set
    to ``target_db``, which is reported as method ``gain_only``."""
    clip = live.any_clip(track_index, clip_index, arrangement, kind="audio")
    if peak_db is None:
        wanted_gain_db, method = target_db, "gain_only"
    else:
        wanted_gain_db, method = target_db - peak_db, "measured_peak"
    before = peek(clip, "gain_display_string")
    gain_before = clip.gain
    reached = _set_gain_db(clip, wanted_gain_db)
    live.record_value("Clip '%s' gain: %s -> %s" % (
        clip.name, before, peek(clip, "gain_display_string")),
        clip, "gain", gain_before, label="the clip gain")
    return {
        "track": track_index,
        "clip": clip_index,
        "clip_name": clip.name,
        "arrangement": arrangement,
        "method": method,
        "target_db": target_db,
        "peak_db": peak_db,
        "gain_db_wanted": round(wanted_gain_db, 2),
        "gain_db_reached": reached,
        "gain_set": clip.gain,
        "gain_before": before,
        "gain_display": peek(clip, "gain_display_string"),
    }


def _shown_gain_db(clip):
    text = str(clip.gain_display_string).lower().replace("db", "").strip()
    if "inf" in text:
        return float("-inf")
    return float(text.replace(",", "."))


def _set_gain_db(clip, wanted_db):
    """Move clip.gain (0..1) until Live displays ``wanted_db``.

    The upper part of Live's gain law is linear at 40 dB per unit with 0 dB
    at 0.4; that gives the first guess. A few corrections against the
    displayed value take care of the curved lower part.
    """
    wanted_db = min(wanted_db, 24.0)
    value = max(0.0, min(1.0, 0.4 + wanted_db / 40.0))
    clip.gain = value
    shown = None
    for _ in range(6):
        try:
            shown = _shown_gain_db(clip)
        except (ValueError, AttributeError, RuntimeError):
            return None
        if shown == float("-inf"):
            if wanted_db < -60.0:
                break
            value = min(1.0, value + 0.05)
        elif abs(shown - wanted_db) < 0.05:
            break
        else:
            value = max(0.0, min(1.0, value + (wanted_db - shown) / 40.0))
        clip.gain = value
    return shown
