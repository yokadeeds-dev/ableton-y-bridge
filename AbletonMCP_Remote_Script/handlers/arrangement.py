# Copyright (C) 2026 Yoka
# SPDX-License-Identifier: AGPL-3.0-only
"""Arrangement view: clips on the timeline and their notes."""

import os

from .. import noteio, warpops
from ..errors import BAD_PARAMS, UNSUPPORTED, CommandError
from ..liveaccess import peek
from ..liveaccess import still_there
from ..registry import READ, REVERSIBLE, Int, Items, command
from .clips import record_notes


def _clip_row(index, clip):
    row = {
        "index": index,
        "name": peek(clip, "name", "?"),
        "start_time": float(peek(clip, "start_time", 0.0)),
        "end_time": float(peek(clip, "end_time", 0.0)),
        "length": float(peek(clip, "length", 0.0)),
        "is_midi": bool(peek(clip, "is_midi_clip", False)),
        "muted": bool(peek(clip, "muted", False)),
    }
    if peek(clip, "is_audio_clip", False):
        markers = peek(clip, "warp_markers")
        row.update({
            "warping": bool(peek(clip, "warping", False)),
            "warp_mode": int(peek(clip, "warp_mode", 0)),
            "warp_marker_count": len(markers) if markers is not None else 0,
            "file_path": peek(clip, "file_path"),
        })
    return row


@command("get_arrangement_clips", zone=READ,
         summary="Clips of one track in the Arrangement, with warp state",
         params=[Int("track_index")])
def get_arrangement_clips(live, track_index):
    clips = live.arrangement_clips(track_index)
    return {
        "track_index": track_index,
        "track": live.track(track_index).name,
        "clips": [_clip_row(i, clip) for i, clip in enumerate(clips)],
    }


@command("get_arrangement_midi_notes", zone=READ,
         summary="All notes of an Arrangement MIDI clip",
         params=[Int("track_index"), Int("clip_index")])
def get_arrangement_midi_notes(live, track_index, clip_index):
    clip = live.arrangement_clip(track_index, clip_index, kind="midi")
    notes = noteio.read(clip)
    return {
        "track": live.track(track_index).name,
        "clip": clip.name,
        "clip_start": float(clip.start_time),
        "clip_length": float(clip.length),
        "note_count": len(notes),
        "notes": notes,
    }


@command("replace_arrangement_clip_notes", zone=REVERSIBLE,
         summary="Replace all notes of an Arrangement MIDI clip in one step",
         params=[Int("track_index"), Int("clip_index"), Items("notes")])
def replace_arrangement_clip_notes(live, track_index, clip_index, notes):
    clip = live.arrangement_clip(track_index, clip_index, kind="midi")
    cleaned = noteio.normalise(notes)
    before = noteio.read(clip)
    removed = len(before)
    written = noteio.replace_all(clip, cleaned, live.live_module())
    record_notes(live, clip, before, "Replaced the notes of arrangement clip '%s': "
                 "%d -> %d notes" % (clip.name, removed, written))
    return {"written": written, "removed": removed, "clip": clip.name}


def _record_new_clips(live, track, present, file_name):
    fresh = [clip for clip in track.arrangement_clips if still_there(clip, present) < 0]
    text = "Placed '%s' on '%s' in the Arrangement" % (file_name, track.name)
    remover = peek(track, "delete_clip")
    if not fresh or not callable(remover):
        live.record(text, kind="live_undo")
        return

    def valid():
        if all(still_there(clip, track.arrangement_clips) >= 0 for clip in fresh):
            return None
        return "the clip is no longer on the track"

    def undo():
        for clip in fresh:
            track.delete_clip(clip)
        return {"removed_clips": len(fresh)}

    live.record(text, undo, valid)


@command("create_arrangement_audio_clips", zone=REVERSIBLE,
         summary="Place audio files on the Arrangement timeline",
         params=[Items("clips", doc="[{track, file_path, position}]")], timeout=60.0)
def create_arrangement_audio_clips(live, clips):
    results = []
    for entry in clips:
        try:
            track_index = int(entry["track"])
            file_path = str(entry["file_path"])
            position = float(entry.get("position", 0.0))
        except (KeyError, TypeError, ValueError):
            raise CommandError(BAD_PARAMS, "each clip needs track, file_path and position")
        row = {"track": track_index, "file": os.path.basename(file_path), "position": position}
        try:
            track = live.track(track_index)
            maker = peek(track, "create_audio_clip")
            if not callable(maker):
                raise CommandError(UNSUPPORTED,
                                   "this Live version cannot create arrangement audio clips")
            if not os.path.isfile(file_path):
                raise CommandError(BAD_PARAMS, "file not found: %s" % file_path)
            present = list(track.arrangement_clips)
            maker(file_path, position)
            row["ok"] = True
            _record_new_clips(live, track, present, row["file"])
        except Exception as problem:  # report per clip, keep going
            row["ok"] = False
            row["error"] = str(problem)
        results.append(row)
    return {"clips_created": results,
            "succeeded": sum(1 for r in results if r["ok"]),
            "failed": sum(1 for r in results if not r["ok"])}


@command("repair_arrangement_warp", zone=REVERSIBLE,
         summary="Reset warping of Arrangement audio clips to a start and an end marker",
         params=[Items("clips", doc="[{track, clip, end_beat, mode?, name?}]")], timeout=30.0)
def repair_arrangement_warp(live, clips):
    """Switch warping on, set the warp mode, drop all inner markers and move
    the trailing markers so the audio ends at ``end_beat``."""
    results = []
    for entry in clips:
        try:
            track_index = int(entry["track"])
            clip_index = int(entry.get("clip", 0))
            end_beat = float(entry["end_beat"])
            mode = int(entry.get("mode", 4))
        except (KeyError, TypeError, ValueError):
            raise CommandError(BAD_PARAMS, "each entry needs track and end_beat")
        row = {"track": track_index, "clip": clip_index}
        try:
            clip = live.arrangement_clip(track_index, clip_index, kind="audio")
            clip.warping = True
            clip.warp_mode = mode
            removed = 0
            for marker in warpops.read(clip):
                try:
                    warpops.remove(clip, marker["beat_time"])
                    removed += 1
                except Exception:
                    pass  # Live keeps the markers it needs
            trailing = [m for m in warpops.read(clip) if m["beat_time"] > 0.1]
            if trailing:
                first = trailing[0]["beat_time"]
                # Last one first, so markers never cross on the way.
                for marker in sorted(trailing, key=lambda m: -m["beat_time"]):
                    warpops.move(clip, marker["beat_time"],
                                 end_beat + (marker["beat_time"] - first))
            try:
                clip.loop_end = end_beat
            except Exception:
                pass
            if entry.get("name"):
                clip.name = str(entry["name"])
            row.update({
                "ok": bool(trailing),
                "warping": bool(clip.warping),
                "warp_mode": int(clip.warp_mode),
                "markers_removed": removed,
                "markers": warpops.read(clip),
            })
        except Exception as problem:
            row.update({"ok": False, "error": str(problem)})
        results.append(row)
    return {"warp_fixed": results}


@command("probe_arrangement_api", zone=READ,
         summary="List clip/arrangement related members of Song and Track (diagnostic)")
def probe_arrangement_api(live):
    def members(obj):
        return sorted(n for n in dir(obj) if "clip" in n.lower() or "arrange" in n.lower())

    tracks = live.song.tracks
    return {
        "song": members(live.song),
        "track": members(tracks[0]) if len(tracks) else [],
    }
