# Copyright (C) 2026 Yoka
# SPDX-License-Identifier: AGPL-3.0-only
"""Song, transport, scenes, views, undo and bridge maintenance."""

from __future__ import annotations

from ..coerce import BoolLike, FloatLike, IntLike, to_bool, to_float, to_int
from ..core import READ, REVERSIBLE, TOOLS, analyzer, live, tool


@tool(READ)
def get_session_info() -> str:
    """Overview of the open Live Set.

    Returns tempo, time signature, transport and loop state, the list of
    tracks (index, name, kind), return tracks, scene and locator counts and
    the master fader. Start here; indices from this list are what the other
    tools expect.
    """
    return live.call("get_session_info")


@tool(REVERSIBLE)
def set_tempo(tempo: FloatLike) -> str:
    """Set the song tempo.

    - tempo: beats per minute, 20 to 999
    """
    result = live.call("set_tempo", tempo=to_float(tempo, "tempo"))
    return f"Tempo is now {result['tempo']:.2f} BPM (was {result['previous_tempo']:.2f})."


@tool(REVERSIBLE)
def start_playback() -> str:
    """Start Live's transport from the current position."""
    result = live.call("start_playback")
    return f"Playing from beat {result['song_time_beats']:.2f}."


@tool(REVERSIBLE)
def stop_playback() -> str:
    """Stop Live's transport."""
    result = live.call("stop_playback")
    return f"Stopped at beat {result['song_time_beats']:.2f}."


@tool(REVERSIBLE)
def undo() -> str:
    """Undo the most recent change in Live (same as Ctrl+Z)."""
    result = live.call("undo")
    return "Undone." if result.get("undone") else f"Nothing undone: {result.get('reason')}."


@tool(REVERSIBLE)
def redo() -> str:
    """Redo the change that was undone last (same as Ctrl+Y)."""
    result = live.call("redo")
    return "Redone." if result.get("redone") else f"Nothing redone: {result.get('reason')}."


@tool(REVERSIBLE)
def set_arrangement_record(enabled: BoolLike) -> str:
    """Switch the global Arrangement Record button on or off.

    Typical use: arm, launch a scene, wait, stop playback, then look at the
    Arrangement view.

    - enabled: true arms recording into the Arrangement, false disarms
    """
    result = live.call("set_arrangement_record", enabled=to_bool(enabled, "enabled"))
    return "Arrangement Record is " + ("ON." if result["record_mode"] else "off.")


@tool(REVERSIBLE)
def fire_scene(scene_index: IntLike) -> str:
    """Launch a scene: all clips of that Session row start together.

    - scene_index: 0 is the top row
    """
    result = live.call("fire_scene", scene_index=to_int(scene_index, "scene_index"))
    return f"Launched scene {result['scene_index']} '{result['scene_name']}'."


@tool(REVERSIBLE)
def set_scene_tempo(scene_index: IntLike, tempo: FloatLike) -> str:
    """Give a scene its own tempo; Live switches to it when the scene is launched.

    - scene_index: 0 is the top row
    - tempo: beats per minute, 20 to 999
    """
    result = live.call("set_scene_tempo", scene_index=to_int(scene_index, "scene_index"),
                       tempo=to_float(tempo, "tempo"))
    return (f"Scene {result['scene_index']} '{result['scene_name']}' now carries "
            f"{result['tempo']:.2f} BPM.")


@tool(READ)
def switch_view(view: str) -> str:
    """Show one of Live's main views.

    - view: Session, Arranger, Browser, Detail, Clip (clip detail) or Device
            (device chain)
    """
    result = live.call("switch_view", view=view)
    return f"Showing the {result['view']} view."


@tool(READ)
def focus_view(view: str) -> str:
    """Show a view and move the keyboard focus to it.

    - view: Session, Arranger, Browser, Detail, Clip or Device
    """
    result = live.call("focus_view", view=view)
    return f"The {result['focused']} view has the focus."


@tool(REVERSIBLE)
def jump_to_time(time: FloatLike) -> str:
    """Move the Arrangement play position.

    - time: position in beats from the start of the song (0 = bar 1)
    """
    result = live.call("jump_to_time", time=to_float(time, "time"))
    return f"Play position is at beat {result['time']:.3f}."


@tool(REVERSIBLE)
def set_arrangement_loop(start: FloatLike, length: FloatLike, enabled: BoolLike = True) -> str:
    """Set the Arrangement loop brace.

    - start: loop start in beats
    - length: loop length in beats
    - enabled: switch the loop on (default) or off
    """
    result = live.call("set_arrangement_loop", start=to_float(start, "start"),
                       length=to_float(length, "length"), enabled=to_bool(enabled, "enabled"))
    state = "on" if result["enabled"] else "off"
    return f"Loop {result['start']:g} to {result['end']:g} beats, {state}."


@tool(READ)
def hot_reload() -> str:
    """Reload the Remote Script's command handlers from disk while Live keeps running.

    Use after editing files of the Remote Script. The socket server and the
    other core modules are not replaced; if they changed, the answer says a
    restart of Live is needed. On an error the previous handlers stay active.
    """
    result = live.call("hot_reload")
    if result.get("hot_reload") != "ok":
        return f"Hot reload failed, previous handlers kept: {result.get('reason')}"
    text = (f"Hot reload ok: {result['commands']} commands from "
            f"{result['modules_reloaded']} modules, source hash {result['file_hash']}.")
    if result.get("added"):
        text += f" New: {', '.join(result['added'])}."
    if result.get("removed"):
        text += f" Gone: {', '.join(result['removed'])}."
    if result.get("core_changed"):
        text += " " + result["note"]
    live.close()  # fetch the new register on the next call
    return text


@tool(READ)
def bridge_status() -> str:
    """Version and health check of the bridge between this server and Live.

    Reports the Remote Script version, how many commands it offers, a hash
    of its source files as loaded from disk, whether a restart of Live is
    pending after core changes, and Live's own version. ``analyzer_feed``
    says whether this server owns the analyzer port ("hub") or gets copies
    of the frames from the server that owns it ("relayed").
    """
    result = live.call("get_version")
    zones = {"read": 0, "reversible": 0, "destructive": 0}
    for entry in TOOLS.values():
        zones[entry["zone"]] += 1
    result["mcp_tools"] = len(TOOLS)
    result["mcp_tools_by_zone"] = zones
    result["analyzer_feed"] = {"udp_port": analyzer.port, "role": analyzer.role,
                               "servers_receiving_copies": analyzer.subscribers}
    return result
