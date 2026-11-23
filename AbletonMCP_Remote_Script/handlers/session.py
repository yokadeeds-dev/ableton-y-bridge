# Copyright (C) 2026 Yoka
# SPDX-License-Identifier: AGPL-3.0-only
"""Song-level commands: overview, tempo, transport, scenes, views, undo."""

from ..errors import BAD_PARAMS, NOT_FOUND, UNSUPPORTED, CommandError
from ..liveaccess import db_of, peek, same, track_kind
from ..registry import (
    DESTRUCTIVE,
    READ,
    REVERSIBLE,
    Bool,
    Float,
    Int,
    Later,
    Text,
    command,
)

_VIEW_NAMES = {
    "session": "Session",
    "arranger": "Arranger",
    "arrangement": "Arranger",
    "browser": "Browser",
    "detail": "Detail",
    "clip": "Detail/Clip",
    "detail/clip": "Detail/Clip",
    "device": "Detail/DeviceChain",
    "devices": "Detail/DeviceChain",
    "detail/devicechain": "Detail/DeviceChain",
}


def _view_name(live, wanted):
    name = _VIEW_NAMES.get(str(wanted).strip().lower())
    known = list(peek(live.app.view, "available_main_views", lambda: [])())
    if name is None and wanted in known:
        name = wanted
    if name is None:
        raise CommandError(
            NOT_FOUND, "unknown view '%s'" % wanted,
            available_views=known or sorted(set(_VIEW_NAMES.values())),
        )
    return name


def _safe_db(parameter):
    try:
        return db_of(parameter)
    except Exception:
        return None


@command("get_session_info", zone=READ,
         summary="Overview of the Live Set: tempo, metre, transport, track list")
def get_session_info(live):
    song = live.song
    master = song.master_track
    tracks = []
    for index, track in enumerate(song.tracks):
        tracks.append({"index": index, "name": track.name, "kind": track_kind(track)})
    returns = [{"index": i, "name": t.name} for i, t in enumerate(song.return_tracks)]
    return {
        "set_name": peek(song, "name"),
        "set_path": peek(song, "file_path"),
        "tempo": song.tempo,
        "signature_numerator": song.signature_numerator,
        "signature_denominator": song.signature_denominator,
        "is_playing": bool(song.is_playing),
        "song_time_beats": song.current_song_time,
        "record_mode": bool(peek(song, "record_mode", False)),
        "loop": {
            "enabled": bool(song.loop),
            "start": song.loop_start,
            "length": song.loop_length,
        },
        "track_count": len(tracks),
        "return_track_count": len(returns),
        "scene_count": len(song.scenes),
        "locator_count": len(song.cue_points),
        "tracks": tracks,
        "return_tracks": returns,
        "master_track": {
            "name": master.name,
            "volume": master.mixer_device.volume.value,
            "volume_db": _safe_db(master.mixer_device.volume),
            "panning": master.mixer_device.panning.value,
        },
    }


@command("set_tempo", zone=REVERSIBLE, summary="Set the song tempo in BPM",
         params=[Float("tempo")])
def set_tempo(live, tempo):
    if not 20.0 <= tempo <= 999.0:
        raise CommandError(BAD_PARAMS, "tempo must be within 20..999 BPM, got %s" % tempo)
    song = live.song
    before = song.tempo
    song.tempo = tempo
    live.record_value("Tempo: %.2f -> %.2f BPM" % (before, song.tempo), song, "tempo", before)
    return {"tempo": song.tempo, "previous_tempo": before}


@command("start_playback", zone=REVERSIBLE, undo="none", journal=False,
         summary="Start the transport")
def start_playback(live):
    song = live.song
    song.start_playing()
    return Later(lambda: {"is_playing": bool(song.is_playing),
                          "song_time_beats": song.current_song_time})


@command("stop_playback", zone=REVERSIBLE, undo="none", journal=False,
         summary="Stop the transport")
def stop_playback(live):
    song = live.song
    song.stop_playing()
    return Later(lambda: {"is_playing": bool(song.is_playing),
                          "song_time_beats": song.current_song_time})


@command("jump_to_time", zone=REVERSIBLE, undo="none", journal=False,
         summary="Move the arrangement play position (beats)",
         params=[Float("time")])
def jump_to_time(live, time):
    if time < 0:
        raise CommandError(BAD_PARAMS, "time must not be negative")
    song = live.song
    song.current_song_time = time
    return Later(lambda: {"time": song.current_song_time, "requested": time})


def _apply_loop(song, start, length, enabled):
    # Order matters: Live rejects a start beyond the current loop end.
    if start >= song.loop_start + song.loop_length:
        song.loop_length = (start - song.loop_start) + length
    song.loop_start = start
    song.loop_length = length
    song.loop = enabled


@command("set_arrangement_loop", zone=REVERSIBLE,
         summary="Set the arrangement loop brace and switch it on or off",
         params=[Float("start"), Float("length"), Bool("enabled", True)])
def set_arrangement_loop(live, start, length, enabled):
    if start < 0 or length <= 0:
        raise CommandError(BAD_PARAMS, "loop needs start >= 0 and length > 0")
    song = live.song
    before = (song.loop_start, song.loop_length, bool(song.loop))
    _apply_loop(song, start, length, enabled)

    def valid():
        if (same(song.loop_start, start) and same(song.loop_length, length)
                and bool(song.loop) == enabled):
            return None
        return "the loop was changed since"

    def undo():
        _apply_loop(song, *before)
        return {"restored": "loop"}

    live.record("Loop: %g+%g %s -> %g+%g %s" % (
        before[0], before[1], "on" if before[2] else "off",
        start, length, "on" if enabled else "off"), undo, valid)
    return Later(lambda: {
        "start": song.loop_start,
        "length": song.loop_length,
        "end": song.loop_start + song.loop_length,
        "enabled": bool(song.loop),
    })


@command("set_arrangement_record", zone=REVERSIBLE, undo="none", journal=False,
         summary="Arm or disarm the global Arrangement Record button",
         params=[Bool("enabled")])
def set_arrangement_record(live, enabled):
    song = live.song
    song.record_mode = enabled
    return Later(lambda: {"record_mode": bool(song.record_mode)})


@command("fire_scene", zone=REVERSIBLE, undo="none", journal=False,
         summary="Launch a scene",
         params=[Int("scene_index")])
def fire_scene(live, scene_index):
    scene = live.scene(scene_index)
    scene.fire()
    return {"scene_index": scene_index, "scene_name": scene.name}


@command("set_scene_tempo", zone=REVERSIBLE,
         summary="Give a scene its own tempo (applied when the scene is launched)",
         params=[Int("scene_index"), Float("tempo")])
def set_scene_tempo(live, scene_index, tempo):
    if not 20.0 <= tempo <= 999.0:
        raise CommandError(BAD_PARAMS, "tempo must be within 20..999 BPM, got %s" % tempo)
    scene = live.scene(scene_index)
    if peek(scene, "tempo") is None:
        raise CommandError(UNSUPPORTED, "this Live version has no per-scene tempo")
    has_switch = peek(scene, "tempo_enabled") is not None
    before = (scene.tempo, bool(scene.tempo_enabled) if has_switch else True)
    if has_switch:
        scene.tempo_enabled = True
    scene.tempo = tempo

    def valid():
        return None if same(scene.tempo, tempo) else "the scene tempo was changed since"

    def undo():
        scene.tempo = before[0]
        if has_switch:
            scene.tempo_enabled = before[1]
        return {"restored": "scene tempo"}

    live.record("Scene %d tempo: %s -> %.2f BPM" % (
        scene_index, "%.2f" % before[0] if before[1] else "none", tempo), undo, valid)
    return {"scene_index": scene_index, "scene_name": scene.name, "tempo": scene.tempo}


@command("switch_view", zone=READ, summary="Show one of Live's main views",
         params=[Text("view")])
def switch_view(live, view):
    name = _view_name(live, view)
    live.app.view.show_view(name)
    return {"view": name, "visible": bool(live.app.view.is_view_visible(name))}


@command("focus_view", zone=READ, summary="Show a view and give it the keyboard focus",
         params=[Text("view", "Session")])
def focus_view(live, view):
    name = _view_name(live, view)
    live.app.view.show_view(name)
    live.app.view.focus_view(name)
    return {"focused": name}


@command("undo", zone=REVERSIBLE, undo="none", summary="Undo the last step in Live")
def undo(live):
    if not peek(live.song, "can_undo", True):
        live.quiet()
        return {"undone": False, "reason": "nothing to undo"}
    live.song.undo()
    live.record("Live undo (Ctrl+Z)", kind="none")
    return {"undone": True}


@command("redo", zone=REVERSIBLE, undo="none", summary="Redo the step undone last")
def redo(live):
    if not peek(live.song, "can_redo", True):
        live.quiet()
        return {"redone": False, "reason": "nothing to redo"}
    live.song.redo()
    live.record("Live redo (Ctrl+Y)", kind="none")
    return {"redone": True}


@command("save_project", zone=DESTRUCTIVE,
         summary="Save the Live Set (only where Live's API offers it)")
def save_project(live):
    saver = peek(live.song, "save_project")
    if not callable(saver):
        # Live 12 has no save call, and its Python lacks ctypes, so the
        # shortcut cannot be typed from in here either.
        raise CommandError(
            UNSUPPORTED,
            "Live's API cannot save a Set. The MCP tool snapshot_session sends "
            "Ctrl+S to Live's window instead.",
        )
    saver()
    return {"saved": True, "method": "api", "set_path": peek(live.song, "file_path")}
