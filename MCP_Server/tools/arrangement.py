# Copyright (C) 2026 Yoka
# SPDX-License-Identifier: AGPL-3.0-only
"""Arrangement view: clips on the timeline, warp markers, locators."""

from __future__ import annotations

import json

from ..coerce import BoolLike, FloatLike, IntLike, to_float, to_int, to_list
from ..core import DESTRUCTIVE, READ, REVERSIBLE, _without_journal, live, tool

WARP_MODE_NAMES = {0: "Beats", 1: "Tones", 2: "Texture", 3: "Re-Pitch", 4: "Complex",
                   5: "REX", 6: "Complex Pro"}
_KEYWORDS = ("reload", "version", "save", "warp_intel", "tempo", "probe")


@tool(READ)
def get_arrangement_clips(track_index: IntLike) -> str:
    """List the clips of one track in the Arrangement view.

    Per clip: index, name, start and length in beats and, for audio clips,
    whether warping is on, the warp mode and the number of warp markers.
    The clip index printed here is what the warp tools expect.

    - track_index: track number, counting from 0
    """
    index = to_int(track_index, "track_index")
    result = live.call("get_arrangement_clips", track_index=index)
    clips = result["clips"]
    if not clips:
        return f"Track {index} '{result['track']}' has no Arrangement clips."
    rows = [f"Track {index} '{result['track']}': {len(clips)} Arrangement clip(s)"]
    for clip in clips:
        row = (f"  [{clip['index']}] {clip['name']} | start {clip['start_time']:.2f} "
               f"len {clip['length']:.2f}")
        if clip["is_midi"]:
            row += " | MIDI"
        else:
            mode = WARP_MODE_NAMES.get(clip.get("warp_mode"), "?")
            warped = "warped" if clip.get("warping") else "unwarped"
            row += f" | audio, {warped}, {mode}, {clip.get('warp_marker_count', 0)} markers"
        rows.append(row)
    return "\n".join(rows)


@tool(REVERSIBLE)
def set_clip_warp_mode(track_index: IntLike, clip_index: IntLike, mode: IntLike = 4) -> str:
    """Choose the warp mode of an Arrangement audio clip; warping is switched on.

    - track_index: track number, counting from 0
    - clip_index: clip index from get_arrangement_clips
    - mode: 0 Beats, 1 Tones, 2 Texture, 3 Re-Pitch, 4 Complex,
            5 or 6 Complex Pro. Complex suits full mixes and stems.
    """
    result = live.call("set_clip_warp_mode", track_index=to_int(track_index, "track_index"),
                       clip_index=to_int(clip_index, "clip_index"), mode=to_int(mode, "mode"))
    return (f"Track {result['track']} clip {result['clip']}: warp mode "
            f"{result['warp_mode_name']}, warping {'on' if result['warping'] else 'off'}.")


@tool(READ)
def get_warp_markers(track_index: IntLike, clip_index: IntLike) -> str:
    """List the warp markers of an Arrangement audio clip.

    Each marker pins a position in the audio file (seconds) to a position on
    the timeline (beats, relative to the clip). Markers more than 0.05 beats
    away from the nearest half beat are flagged as off-grid.

    - track_index: track number, counting from 0
    - clip_index: clip index from get_arrangement_clips
    """
    result = live.call("get_warp_markers", track_index=to_int(track_index, "track_index"),
                       clip_index=to_int(clip_index, "clip_index"))
    markers = result["warp_markers"]
    if not markers:
        return f"'{result['clip_name']}' has no warp markers."
    rows = [f"'{result['clip_name']}': {len(markers)} warp markers"
            + ("" if result.get("warping") else " (warping is off)")]
    for marker in markers:
        beat = marker["beat_time"]
        drift = beat - round(beat * 2) / 2
        flag = f"  off-grid {drift:+.3f}" if abs(drift) > 0.05 else ""
        rows.append(f"  beat {beat:10.4f}  <-  {marker['sample_time']:10.4f} s{flag}")
    return "\n".join(rows)


@tool(REVERSIBLE)
def set_warp_marker(track_index: IntLike, clip_index: IntLike,
                    beat_time: FloatLike, sample_time: FloatLike) -> str:
    """Pin a point of the audio to a point on the timeline (one warp marker).

    If a marker already holds this audio position it is moved; otherwise a
    marker is created.

    - track_index: track number, counting from 0
    - clip_index: clip index from get_arrangement_clips
    - beat_time: where the audio should sound, in beats relative to the clip
    - sample_time: position in the audio file in seconds
    """
    result = live.call("set_warp_marker", track_index=to_int(track_index, "track_index"),
                       clip_index=to_int(clip_index, "clip_index"),
                       beat_time=to_float(beat_time, "beat_time"),
                       sample_time=to_float(sample_time, "sample_time"))
    return (f"Warp marker {result['action']}: {result['sample_time']:.4f} s at beat "
            f"{result['beat_time']:.4f}.")


@tool(REVERSIBLE)
def set_warp_markers_batch(track_index: str, clip_index: IntLike, markers: str) -> str:
    """Set several warp markers on one Arrangement audio clip in a single call.

    - track_index: track number, counting from 0
    - clip_index: clip index from get_arrangement_clips
    - markers: JSON array, e.g.
               [{"beat_time": 0.0, "sample_time": 0.031},
                {"beat_time": 4.0, "sample_time": 2.412}]

    For hundreds of markers prefer als_warp_write, which edits the project
    file and does not depend on Live's marker API.

    Older keyword calls are still accepted through track_index: 'version'
    (same as bridge_status), 'reload' (same as hot_reload), 'save', and
    'warp_intel' with clip_index 'track:clip' and markers holding one
    operation object ({"cmd": "analyze_drift" | "find_nearest" | "drag_to_grid"
    | "nudge" | "quantize_region" | "anchor_and_move" | "get_markers" |
    "multi_clip", ...}).
    """
    word = str(track_index).strip()
    entries = to_list(markers, "markers") if markers else []
    keyword = word in _KEYWORDS or word.startswith(("norm:", "del:"))
    if keyword:
        result = live.call("set_warp_markers_batch", track_index=word,
                           clip_index=clip_index, markers=entries)
        return json.dumps(_without_journal(result), ensure_ascii=False, default=str)
    result = live.call("set_warp_markers_batch", track_index=to_int(word, "track_index"),
                       clip_index=to_int(clip_index, "clip_index"), markers=entries)
    text = (f"Set {result['markers_set']} of {len(entries)} warp markers; "
            f"the clip now has {result['total']}.")
    if result["errors"]:
        text += " Problems: " + json.dumps(result["errors"][:10], ensure_ascii=False)
    return text


@tool(READ)
def get_locators() -> str:
    """List the Arrangement locators in time order (index, name, beat)."""
    return live.call("get_locators")


@tool(REVERSIBLE)
def create_locator(time: FloatLike, name: str = "") -> str:
    """Create a locator in the Arrangement. Playback must be stopped.

    If a locator already sits at that position it is only renamed.

    - time: position in beats
    - name: label for the locator (optional)
    """
    result = live.call("create_locator", time=to_float(time, "time"), name=name)
    verb = "Created" if result["created"] else "Kept existing"
    return f"{verb} locator '{result['name']}' at beat {result['time']:g}."


@tool(REVERSIBLE)
def delete_locator(index: IntLike) -> str:
    """Delete one locator. Playback must be stopped.

    - index: index from get_locators (time order, 0 = first)
    """
    result = live.call("delete_locator", index=to_int(index, "index"))
    gone = result["deleted"]
    return (f"Deleted locator '{gone['name']}' at beat {gone['time']:g}; "
            f"{result['remaining']} left.")


@tool(DESTRUCTIVE)
def clear_locators(confirm: BoolLike = False) -> str:
    """Delete all locators of the Arrangement. Stops playback if it is running.

    - confirm: must be true for the tool to run. Ask the user first; do not
               set it on your own initiative.
    """
    result = live.call("clear_locators")
    text = f"Deleted {result['deleted']} locators, {result['remaining']} left."
    if result.get("was_playing"):
        text += " Playback was stopped for this."
    return text
