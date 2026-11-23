"""Tracks, mixer and return tracks."""

from __future__ import annotations

import time

from .. import winkeys
from ..coerce import BoolLike, FloatLike, IntLike, ListLike, to_bool, to_float, to_int, to_list
from ..core import READ, REVERSIBLE, live, note_outside_change, tool


@tool(READ)
def get_track_info(track_index: IntLike) -> str:
    """Details of one track.

    Returns kind (midi, audio, group), mixer state (fader in dB, pan, mute,
    solo, arm, sends), every Session clip slot and the devices on the track.
    The answer is large for tracks with many slots; do not call it in a loop.

    - track_index: position (from 0) in the track list
    """
    return live.call("get_track_info", track_index=to_int(track_index, "track_index"))


@tool(REVERSIBLE)
def create_midi_track(index: IntLike = -1) -> str:
    """Add a MIDI track.

    - index: position to insert at; -1 appends after the last track
    """
    result = live.call("create_midi_track", index=to_int(index, "index"))
    return f"New MIDI track '{result['name']}' at index {result['index']}."


@tool(REVERSIBLE)
def create_audio_track(index: IntLike = -1) -> str:
    """Add an audio track.

    - index: position to insert at; -1 appends after the last track
    """
    result = live.call("create_audio_track", index=to_int(index, "index"))
    return f"New audio track '{result['name']}' at index {result['index']}."


@tool(REVERSIBLE)
def set_track_name(track_index: IntLike, name: str) -> str:
    """Rename a track.

    - track_index: track number, counting from 0
    - name: the new name
    """
    result = live.call("set_track_name", track_index=to_int(track_index, "track_index"),
                       name=name)
    return f"Track {result['index']}: '{result['previous_name']}' is now '{result['name']}'."


@tool(REVERSIBLE)
def set_track_volume(track_index: IntLike, volume_db: FloatLike) -> str:
    """Set a track fader in dB, as shown on Live's mixer.

    - track_index: track number, counting from 0
    - volume_db: 0 is unity, +6 is the top of the fader, "-inf" closes it
    """
    result = live.call("set_track_volume", track_index=to_int(track_index, "track_index"),
                       volume_db=to_float(volume_db, "volume_db"))
    return (f"Track {result['track_index']} '{result['name']}' fader at {result['display']} "
            f"(raw {result['volume_linear']:.4f}).")


@tool(REVERSIBLE)
def set_track_mute(track_index: IntLike, mute: BoolLike) -> str:
    """Mute or unmute a track.

    - track_index: track number, counting from 0
    - mute: true mutes, false unmutes
    """
    result = live.call("set_track_mute", track_index=to_int(track_index, "track_index"),
                       mute=to_bool(mute, "mute"))
    state = "muted" if result["mute"] else "audible"
    return f"Track {result['track_index']} '{result['name']}' is {state}."


@tool(REVERSIBLE)
def set_track_color(track_index: IntLike, color_index: IntLike) -> str:
    """Colour a track.

    - track_index: track number, counting from 0
    - color_index: index into Live's palette, 0 to 69. Larger values are read
                   as a 24-bit RGB colour (0xRRGGBB) and snapped to the
                   nearest palette colour.
    """
    result = live.call("set_track_color", track_index=to_int(track_index, "track_index"),
                       color_index=to_int(color_index, "color_index"))
    return (f"Track {result['track_index']} '{result['name']}' has palette colour "
            f"{result['color_index']}.")


@tool(REVERSIBLE)
def set_track_send(track_index: IntLike, send_index: IntLike, value: FloatLike) -> str:
    """Set how much of a track goes to a return track.

    - track_index: number (from 0) of the sending track
    - send_index: 0 = Return A, 1 = Return B, ...
    - value: 0.0 (off) to 1.0 (full)
    """
    result = live.call("set_track_send", track_index=to_int(track_index, "track_index"),
                       send_index=to_int(send_index, "send_index"),
                       value=to_float(value, "value"))
    return (f"Send {result['send_index']} of '{result['track']}' at {result['value']:.3f} "
            f"({result['display']}).")


@tool(READ)
def select_tracks(track_indices: ListLike) -> str:
    """Select a track in Live.

    Live's API can select one track only; the first of the given indices is
    selected and the answer says so.

    - track_indices: list of 0-based track indices
    """
    result = live.call("select_tracks", track_indices=to_list(track_indices, "track_indices"))
    text = f"Selected track {result['selected_index']} '{result['selected_name']}'."
    if result.get("hint"):
        text += " " + result["hint"]
    return text


@tool(REVERSIBLE)
def group_tracks(track_indices: ListLike) -> str:
    """Group neighbouring tracks into a Group Track.

    Live has no API call for grouping. The bridge selects the first track,
    then this server brings Live's window to the front and types Up, Shift+Right
    and Ctrl+G (Windows only). The answer says whether a Group Track appeared.

    - track_indices: numbers (from 0) of adjacent tracks, at least two
    """
    indices = to_list(track_indices, "track_indices")
    prepared = live.call("group_tracks", track_indices=indices)
    # Cursor sits on the first slot of the first track: up to its title,
    # extend the selection to the right, group.
    keys = [(winkeys.VK_UP,)]
    keys += [(winkeys.VK_SHIFT, winkeys.VK_RIGHT)] * (prepared["count"] - 1)
    keys.append((winkeys.VK_CONTROL, winkeys.VK_G))
    try:
        winkeys.type_into_live(keys, pause=0.12)
    except winkeys.KeysUnavailable as problem:
        return (f"Not grouped: {problem}. Track {prepared['first_index']} is selected in "
                "Live; select the others with Shift and press Ctrl+G there.")
    time.sleep(0.6)
    after = live.call("get_session_info")
    first = prepared["first_index"]
    row = after["tracks"][first] if first < len(after["tracks"]) else {}
    if row.get("kind") == "group" and after["track_count"] == prepared["track_count"] + 1:
        note_outside_change(f"Grouped {prepared['count']} tracks "
                            f"({', '.join(prepared['track_names'])}) with Ctrl+G",
                            undo="live_undo")
        return (f"Grouped {prepared['count']} tracks ({', '.join(prepared['track_names'])}) "
                f"into '{row['name']}' at index {first}. Later tracks moved down by one.")
    return ("Shortcut sent, but no Group Track appeared at index "
            f"{first}. Check Live: the keys may have gone to another part of the window.")


@tool(READ)
def freeze_track(track_index: IntLike, freeze: BoolLike = True) -> str:
    """Report whether a track is frozen.

    Live's API offers no way to freeze or unfreeze, so this tool cannot
    change the state; it tells you what to do in Live instead.

    - track_index: track number, counting from 0
    - freeze: the state you want (true = frozen)
    """
    result = live.call("freeze_track", track_index=to_int(track_index, "track_index"),
                       freeze=to_bool(freeze, "freeze"))
    state = "frozen" if result["is_frozen"] else "not frozen"
    return f"Track {result['track_index']} '{result['name']}' is {state}. {result['note']}"


@tool(READ)
def get_return_tracks() -> str:
    """List the return tracks with fader level, mute state and devices."""
    return live.call("get_return_tracks")


@tool(REVERSIBLE)
def set_return_track_volume(index: IntLike, volume: FloatLike) -> str:
    """Set the fader of a return track.

    - index: 0 = Return A, 1 = Return B, ...
    - volume: raw fader value 0.0 to 1.0 (0.85 is 0 dB)
    """
    result = live.call("set_return_volume", index=to_int(index, "index"),
                       volume=to_float(volume, "volume"))
    return f"Return {result['index']} '{result['name']}' fader at {result['display']}."
