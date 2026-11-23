# Copyright (C) 2026 Yoka
# SPDX-License-Identifier: AGPL-3.0-only
"""Session clips, MIDI notes, and note-level helpers (patterns, key, curves)."""

from __future__ import annotations

import math
from typing import Optional

from .. import audiofile, music
from ..coerce import (
    BoolLike,
    FloatLike,
    IntLike,
    ListLike,
    opt_float,
    opt_int,
    to_bool,
    to_float,
    to_int,
    to_list,
)
from ..core import READ, REVERSIBLE, live, tool
from ..link import LiveError

@tool(REVERSIBLE)
def create_clip(track_index: IntLike, clip_index: IntLike, length: FloatLike = 4.0) -> str:
    """Create an empty MIDI clip in a Session slot of a MIDI track.

    - track_index: track number, counting from 0
    - clip_index: slot number (from 0) (scene row); the slot must be empty
    - length: clip length in beats (4 = one bar in 4/4)
    """
    result = live.call("create_clip", track_index=to_int(track_index, "track_index"),
                       clip_index=to_int(clip_index, "clip_index"),
                       length=to_float(length, "length"))
    return (f"Created a {result['length']:g}-beat MIDI clip on track "
            f"{result['track_index']}, slot {result['clip_index']}.")


@tool(REVERSIBLE)
def set_clip_name(track_index: IntLike, clip_index: IntLike, name: str) -> str:
    """Rename a Session clip.

    - track_index: track number, counting from 0
    - clip_index: slot number (from 0) holding the clip
    - name: the new name
    """
    result = live.call("set_clip_name", track_index=to_int(track_index, "track_index"),
                       clip_index=to_int(clip_index, "clip_index"), name=name)
    return f"Clip on track {result['track_index']}, slot {result['clip_index']} is now '{result['name']}'."


@tool(REVERSIBLE)
def fire_clip(track_index: IntLike, clip_index: IntLike) -> str:
    """Launch a Session clip (it starts at the next launch quantisation point).

    - track_index: track number, counting from 0
    - clip_index: slot number (from 0) holding the clip
    """
    result = live.call("fire_clip", track_index=to_int(track_index, "track_index"),
                       clip_index=to_int(clip_index, "clip_index"))
    return f"Launched '{result['name']}' (track {result['track_index']}, slot {result['clip_index']})."


@tool(REVERSIBLE)
def stop_clip(track_index: IntLike, clip_index: IntLike) -> str:
    """Stop whatever clip is playing on the track of this slot.

    - track_index: track number, counting from 0
    - clip_index: slot number (from 0) on that track
    """
    result = live.call("stop_clip", track_index=to_int(track_index, "track_index"),
                       clip_index=to_int(clip_index, "clip_index"))
    return f"Stop sent to track {result['track_index']}."


@tool(REVERSIBLE)
def add_notes_to_clip(track_index: IntLike, clip_index: IntLike, notes: ListLike) -> str:
    """Add MIDI notes to a Session clip; notes already in the clip stay.

    Send all notes in one call, never one call per note. To rewrite a clip
    from scratch use replace_notes_in_clip.

    - track_index: track number, counting from 0
    - clip_index: slot number (from 0) holding a MIDI clip
    - notes: list of note objects with pitch (0-127), start_time (beats from
             clip start), duration (beats), velocity (1-127) and optional mute, e.g.
             [{"pitch": 36, "start_time": 0, "duration": 0.25, "velocity": 100},
              {"pitch": 38, "start_time": 1, "duration": 0.25, "velocity": 90}]
    """
    result = live.call("add_notes_to_clip", track_index=to_int(track_index, "track_index"),
                       clip_index=to_int(clip_index, "clip_index"),
                       notes=to_list(notes, "notes"))
    return f"Added {result['added']} notes to '{result['clip']}'."



@tool(REVERSIBLE)
def replace_notes_in_clip(track_index: IntLike, clip_index: IntLike, notes: ListLike) -> str:
    """Replace every note of a Session MIDI clip with a new set, in one step.

    The preferred way to write generated material (drum patterns, bass
    lines, melodies): the old notes are removed and the new ones written
    together, so the clip is never half empty and one undo takes it back.

    - track_index: track number, counting from 0
    - clip_index: slot number (from 0) holding a MIDI clip
    - notes: the complete new content as a list of note objects, e.g. a
             four-on-the-floor kick over one bar:
             [{"pitch": 36, "start_time": 0, "duration": 0.25, "velocity": 100},
              {"pitch": 36, "start_time": 1, "duration": 0.25, "velocity": 100},
              {"pitch": 36, "start_time": 2, "duration": 0.25, "velocity": 100},
              {"pitch": 36, "start_time": 3, "duration": 0.25, "velocity": 100}]
    """
    result = live.call("replace_notes_in_clip", track_index=to_int(track_index, "track_index"),
                       clip_index=to_int(clip_index, "clip_index"),
                       notes=to_list(notes, "notes"))
    return (f"'{result['clip']}' now holds {result['written']} notes "
            f"({result['removed']} removed).")


@tool(REVERSIBLE)
def delete_notes_from_clip(track_index: IntLike, clip_index: IntLike,
                           pitch: Optional[IntLike] = None,
                           start_time: Optional[FloatLike] = None,
                           time_span: Optional[FloatLike] = None) -> str:
    """Delete notes from a Session MIDI clip, all of them or a selection.

    - track_index: track number, counting from 0
    - clip_index: slot number (from 0) holding a MIDI clip
    - pitch: only this MIDI pitch (e.g. 46 = open hi-hat); omit for all pitches
    - start_time: only from this beat on; omit to start at the clip start
    - time_span: only this many beats from start_time; omit for "to the end"

    Examples: pitch=46 removes every open hi-hat; start_time=8 clears
    everything from beat 8 on.
    """
    params = {"track_index": to_int(track_index, "track_index"),
              "clip_index": to_int(clip_index, "clip_index")}
    for key, value in (("pitch", opt_int(pitch, "pitch")),
                       ("start_time", opt_float(start_time, "start_time")),
                       ("time_span", opt_float(time_span, "time_span"))):
        if value is not None:
            params[key] = value
    result = live.call("delete_notes_from_clip", **params)
    return (f"Deleted {result['deleted']} notes from '{result['clip']}', "
            f"{result['remaining']} left.")


@tool(REVERSIBLE)
def humanize_clip(track_index: IntLike, clip_index: IntLike,
                  timing_amount: FloatLike = 0.02, velocity_amount: IntLike = 10) -> str:
    """Loosen a Session MIDI clip by random timing and velocity offsets.

    - track_index: track number, counting from 0
    - clip_index: slot number (from 0) holding a MIDI clip
    - timing_amount: largest shift of a note start in beats, either direction
                     (0.02 is subtle, 0.1 is sloppy)
    - velocity_amount: largest velocity change, either direction
    """
    result = live.call("humanize_clip", track_index=to_int(track_index, "track_index"),
                       clip_index=to_int(clip_index, "clip_index"),
                       timing_amount=to_float(timing_amount, "timing_amount"),
                       velocity_amount=to_int(velocity_amount, "velocity_amount"))
    return f"Humanized {result['note_count']} notes in '{result['clip']}'."


@tool(REVERSIBLE)
def transpose_notes(track_index: IntLike, clip_index: IntLike, semitones: IntLike) -> str:
    """Transpose all notes of a Session MIDI clip.

    Nothing is changed if any note would leave the MIDI range.

    - track_index: track number, counting from 0
    - clip_index: slot number (from 0) holding a MIDI clip
    - semitones: positive is up, negative is down (12 = one octave)
    """
    result = live.call("transpose_notes", track_index=to_int(track_index, "track_index"),
                       clip_index=to_int(clip_index, "clip_index"),
                       semitones=to_int(semitones, "semitones"))
    return (f"Transposed {result['note_count']} notes in '{result['clip']}' by "
            f"{result['semitones']:+d} semitones.")


@tool(REVERSIBLE)
def normalize_clip(track_index: IntLike, clip_index: IntLike,
                   arrangement: BoolLike = True, target_db: FloatLike = 0.0) -> str:
    """Set an audio clip's gain so that its loudest sample reaches a target level.

    The peak is measured from the clip's audio file by this server; Live
    then gets the matching clip gain (limit: Live's clip gain tops out at
    +24 dB). If the file cannot be read, nothing is changed.

    - track_index: track number, counting from 0
    - clip_index: 0-based clip index (Arrangement clip order, or Session slot)
    - arrangement: true = Arrangement clip (default), false = Session slot
    - target_db: wanted peak in dBFS, e.g. 0 or -1
    """
    where = {"track_index": to_int(track_index, "track_index"),
             "clip_index": to_int(clip_index, "clip_index"),
             "arrangement": to_bool(arrangement, "arrangement")}
    info = live.call("get_clip_audio_info", **where)
    path = info.get("file_path")
    if not path:
        raise LiveError("Live did not report an audio file for this clip", "not_found")
    peak_db = audiofile.peak_db(path)
    if peak_db is None:
        return (f"'{info['clip_name']}' is digital silence ({path}); "
                "there is nothing to normalise.")
    result = live.call("normalize_clip", target_db=to_float(target_db, "target_db"),
                       peak_db=peak_db, **where)
    return (f"'{result['clip_name']}': file peak {peak_db:+.2f} dBFS, clip gain "
            f"{result['gain_before']} -> {result['gain_display']} "
            f"(wanted {result['gain_db_wanted']:+.2f} dB for a peak of "
            f"{result['target_db']:+.1f} dBFS).")


@tool(READ)
def get_clip_key(track_index: IntLike, clip_index: IntLike) -> str:
    """Estimate the key of a Session MIDI clip.

    Compares the clip's pitch-class weights (duration times velocity) with
    the Krumhansl-Kessler major and minor profiles for all 24 keys.

    - track_index: track number, counting from 0
    - clip_index: slot number (from 0) holding a MIDI clip

    Returns the best key with its correlation, four runners-up and the
    pitch-class distribution.
    """
    result = live.call("get_clip_notes", track_index=to_int(track_index, "track_index"),
                       clip_index=to_int(clip_index, "clip_index"))
    notes = result.get("notes", [])
    if not notes:
        return {"error": f"'{result.get('clip_name')}' contains no notes"}
    weights = music.pitch_class_weights(notes)
    ranking = music.rank_keys(weights)
    return {
        "clip": result.get("clip_name"),
        "best_key": ranking[0][0],
        "score": ranking[0][1],
        "alternatives": ranking[1:5],
        "pitch_class_distribution": dict(zip(music.NOTE_NAMES, [round(w, 4) for w in weights])),
        "note_count": len(notes),
    }


@tool(READ)
def analyze_midi_session(max_tracks: IntLike = 24, check_harmony: BoolLike = True) -> str:
    """Survey the MIDI clips of the Session view track by track.

    For every MIDI track with clips: note count, most used pitch classes and
    an estimated key. With check_harmony the tracks whose key differs from
    the most common one are listed. Reads all notes of all Session clips, so
    it is slow on big Sets; use get_clip_key for a single clip.

    - max_tracks: look at the first N tracks only
    - check_harmony: add the key comparison across tracks
    """
    limit = to_int(max_tracks, "max_tracks")
    session = live.call("get_session_info")
    report, keys, total_notes = ["MIDI session analysis", ""], {}, 0
    for row in session.get("tracks", [])[:max(0, limit)]:
        if row.get("kind") != "midi":
            continue
        info = live.call("get_track_info", track_index=row["index"])
        filled = [slot for slot in info.get("clip_slots", []) if slot.get("has_clip")]
        if not filled:
            continue
        counts = [0] * 12
        names = []
        for slot in filled:
            names.append((slot.get("clip") or {}).get("name") or f"slot {slot['index']}")
            try:
                clip = live.call("get_clip_notes", track_index=row["index"],
                                 clip_index=slot["index"])
            except LiveError:
                continue  # audio clip on a MIDI track cannot happen, but be safe
            for note in clip.get("notes", []):
                counts[note["pitch"] % 12] += 1
        notes_here = sum(counts)
        total_notes += notes_here
        key = music.key_by_scale_fit(counts)
        keys[row["index"]] = key
        top = sorted(range(12), key=lambda pc: counts[pc], reverse=True)[:5]
        top_text = " ".join(f"{music.NOTE_NAMES[pc]}({counts[pc]})" for pc in top if counts[pc])
        report += [
            f"Track {row['index']}: {row['name']}",
            f"  clips: {', '.join(names[:5])}" + (" ..." if len(names) > 5 else ""),
            f"  notes: {notes_here} | key: {key}",
            f"  most used: {top_text or '-'}",
            "",
        ]
    if not keys:
        return "No MIDI tracks with Session clips found."
    report.append(f"Total: {len(keys)} MIDI tracks, {total_notes} notes")
    if to_bool(check_harmony, "check_harmony") and len(keys) > 1:
        found = list(keys.values())
        common = max(set(found), key=found.count)
        odd = [index for index, key in keys.items() if key != common]
        report += ["", f"Most common key: {common} ({found.count(common)} of {len(found)} tracks)"]
        if odd:
            report += [f"  track {index} is in {keys[index]}" for index in odd]
        else:
            report.append("  all tracks agree")
    return "\n".join(report)


@tool(REVERSIBLE)
def generate_euclidean_rhythm(steps: IntLike, pulses: IntLike, pitch: IntLike,
                              bar_length: FloatLike = 4.0, note_duration: FloatLike = 0.25,
                              velocity: IntLike = 100, rotation: IntLike = 0,
                              track_index: Optional[IntLike] = None,
                              clip_index: Optional[IntLike] = None) -> str:
    """Build a Euclidean rhythm and optionally write it into a Session clip.

    A Euclidean rhythm spreads `pulses` hits as evenly as possible over
    `steps` slots: E(3,8) is the tresillo, E(5,8) the cinquillo, E(4,16)
    four-on-the-floor.

    - steps: number of slots the bar is divided into (16 = sixteenth notes)
    - pulses: number of hits, 0 to steps
    - pitch: MIDI pitch of the hits (36 kick, 38 snare, 42 closed hat)
    - bar_length: length of the pattern in beats
    - note_duration: length of each hit in beats
    - velocity: 1 to 127
    - rotation: shift the pattern left by this many slots
    - track_index, clip_index: if both are given the pattern REPLACES the
      notes of that Session clip; otherwise nothing in Live changes

    Returns the pattern as 0/1 list, the hit positions in beats and the notes.
    """
    slots, hits = to_int(steps, "steps"), to_int(pulses, "pulses")
    if slots <= 0 or not 0 <= hits <= slots:
        raise ValueError("need steps > 0 and 0 <= pulses <= steps")
    turn = to_int(rotation, "rotation")
    pattern = music.euclidean_pattern(slots, hits, turn)
    slot_length = to_float(bar_length, "bar_length") / slots
    length = to_float(note_duration, "note_duration")
    notes = [
        {"pitch": to_int(pitch, "pitch"), "start_time": round(slot * slot_length, 6),
         "duration": length, "velocity": to_int(velocity, "velocity"), "mute": False}
        for slot, hit in enumerate(pattern) if hit
    ]
    answer = {
        "pattern": pattern,
        "steps": slots,
        "pulses": hits,
        "rotation": turn,
        "hit_positions_beats": [note["start_time"] for note in notes],
        "note_count": len(notes),
        "notes": notes,
        "written_to_clip": False,
    }
    target_track, target_clip = opt_int(track_index, "track_index"), opt_int(clip_index, "clip_index")
    if target_track is not None and target_clip is not None:
        try:
            live.call("replace_notes_in_clip", track_index=target_track,
                      clip_index=target_clip, notes=notes)
            answer.update(written_to_clip=True, track_index=target_track, clip_index=target_clip)
        except LiveError as problem:
            answer["write_error"] = str(problem)
    return answer


@tool(READ)
def generate_automation_curve(curve_type: str, steps: IntLike,
                              value_min: FloatLike = 0.0, value_max: FloatLike = 1.0,
                              bar_length: FloatLike = 4.0, cycles: FloatLike = 1.0,
                              phase_offset: FloatLike = 0.0) -> str:
    """Compute an automation shape as a list of (beat, value) points.

    Produces data only; nothing is written to Live. Feed the points to
    set_device_parameter step by step or use them elsewhere.

    - curve_type: sine, cosine, triangle, sawtooth, reverse_saw, square,
                  exponential, logarithmic, s_curve, random, envelope, bounce
    - steps: number of points (at least 2)
    - value_min, value_max: output range
    - bar_length: time span of the curve in beats
    - cycles: repetitions within the span (periodic shapes and bounce)
    - phase_offset: 0..1, shifts periodic shapes by a fraction of a cycle
    """
    count = to_int(steps, "steps")
    if count < 2:
        raise ValueError("steps must be at least 2")
    shape = curve_type.strip().lower()
    if shape not in music.CURVES:
        raise ValueError(f"unknown curve_type '{curve_type}'; "
                         f"choose from {', '.join(sorted(music.CURVES))}")
    low, high = to_float(value_min, "value_min"), to_float(value_max, "value_max")
    span, repeats = to_float(bar_length, "bar_length"), to_float(cycles, "cycles")
    phase = to_float(phase_offset, "phase_offset")
    points = []
    for step in range(count):
        progress = step / (count - 1)
        unit = music.CURVES[shape](progress, (progress * repeats + phase) % 1.0, repeats)
        points.append({"beat": round(progress * span, 6),
                       "value": round(low + unit * (high - low), 6)})
    if math.isclose(low, high):
        note = "value_min equals value_max: the curve is flat"
    else:
        note = ""
    return {"curve_type": shape, "steps": count, "value_min": low, "value_max": high,
            "bar_length": span, "cycles": repeats, "point_count": len(points),
            "points": points, "note": note}
