# Copyright (C) 2026 Yoka
# SPDX-License-Identifier: AGPL-3.0-only
"""Track and mixer commands."""

import math

from ..errors import BAD_PARAMS, CommandError, out_of_range
from ..liveaccess import db_of, peek, pick, still_there, track_kind, value_for_db
from ..registry import (
    DESTRUCTIVE,
    READ,
    REVERSIBLE,
    Bool,
    Float,
    Int,
    Items,
    Text,
    command,
)

_PALETTE_SIZE = 70  # Live's track colour palette has indices 0..69


def _device_role(device):
    if peek(device, "can_have_drum_pads", False):
        return "drum_rack"
    if peek(device, "can_have_chains", False):
        return "rack"
    kind = str(peek(device, "type", "")).lower()
    for word, role in (("instrument", "instrument"), ("audio_effect", "audio_effect"),
                       ("midi_effect", "midi_effect")):
        if word in kind:
            return role
    return "device"


def _device_rows(track):
    rows = []
    for index, device in enumerate(track.devices):
        rows.append({
            "index": index,
            "name": device.name,
            "class_name": peek(device, "class_name", ""),
            "type": _device_role(device),
            "is_active": bool(peek(device, "is_active", True)),
        })
    return rows


def _slot_rows(track):
    rows = []
    for index, slot in enumerate(track.clip_slots):
        entry = {"index": index, "has_clip": bool(slot.has_clip), "clip": None}
        if slot.has_clip:
            clip = slot.clip
            entry["clip"] = {
                "name": clip.name,
                "length": clip.length,
                "is_midi": bool(peek(clip, "is_midi_clip", False)),
                "is_playing": bool(clip.is_playing),
                "is_recording": bool(clip.is_recording),
            }
        rows.append(entry)
    return rows


def _fader_db(parameter):
    try:
        return db_of(parameter)
    except Exception:
        return None


@command("get_track_info", zone=READ,
         summary="One track: kind, mixer state, clip slots, devices",
         params=[Int("track_index")])
def get_track_info(live, track_index):
    track = live.track(track_index)
    mixer = track.mixer_device
    kind = track_kind(track)
    return {
        "index": track_index,
        "name": track.name,
        "kind": kind,
        "is_midi_track": kind == "midi",
        "is_audio_track": kind == "audio",
        "is_group_track": kind == "group",
        "is_grouped": bool(peek(track, "is_grouped", False)),
        "color_index": peek(track, "color_index"),
        "mute": bool(peek(track, "mute", False)),
        "solo": bool(peek(track, "solo", False)),
        "arm": bool(peek(track, "arm", False)) if peek(track, "can_be_armed", False) else None,
        "is_frozen": bool(peek(track, "is_frozen", False)),
        "volume": mixer.volume.value,
        "volume_db": _fader_db(mixer.volume),
        "panning": mixer.panning.value,
        "sends": [round(send.value, 4) for send in mixer.sends],
        "clip_slots": _slot_rows(track),
        "arrangement_clip_count": len(peek(track, "arrangement_clips", ()) or ()),
        "devices": _device_rows(track),
    }


def _new_track(live, creator, index, kind):
    song = live.song
    count = len(song.tracks)
    if index < -1 or index > count:
        raise out_of_range("insert position", index, count + 1)
    creator(index)
    position = len(song.tracks) - 1 if index == -1 else index
    track = song.tracks[position]

    def valid():
        return None if still_there(track, song.tracks) >= 0 else "the track no longer exists"

    def undo():
        song.delete_track(still_there(track, song.tracks))
        return {"deleted_track": True}

    live.record("Created %s track '%s' at index %d" % (kind, track.name, position), undo, valid)
    return {"index": position, "name": track.name}


@command("create_midi_track", zone=REVERSIBLE,
         summary="Insert a MIDI track (-1 = after the last track)",
         params=[Int("index", -1)])
def create_midi_track(live, index):
    return _new_track(live, live.song.create_midi_track, index, "MIDI")


@command("create_audio_track", zone=REVERSIBLE,
         summary="Insert an audio track (-1 = after the last track)",
         params=[Int("index", -1)])
def create_audio_track(live, index):
    return _new_track(live, live.song.create_audio_track, index, "audio")


@command("delete_track", zone=DESTRUCTIVE, undo="live",
         summary="Delete a track with everything on it",
         params=[Int("track_index")])
def delete_track(live, track_index):
    name = live.track(track_index).name
    live.song.delete_track(track_index)
    live.record("Deleted track '%s' (was index %d)" % (name, track_index), kind="live_undo")
    return {"deleted": True, "index": track_index, "name": name,
            "track_count": len(live.song.tracks)}


@command("set_track_name", zone=REVERSIBLE, summary="Rename a track",
         params=[Int("track_index"), Text("name")])
def set_track_name(live, track_index, name):
    track = live.track(track_index)
    before = track.name
    track.name = name
    live.record_value("Track %d name: '%s' -> '%s'" % (track_index, before, track.name),
                      track, "name", before)
    return {"index": track_index, "name": track.name, "previous_name": before}


@command("set_track_volume", zone=REVERSIBLE,
         summary="Set a track fader to a level in dB (as Live displays it)",
         params=[Int("track_index"), Float("volume_db")])
def set_track_volume(live, track_index, volume_db):
    track = live.track(track_index)
    fader = track.mixer_device.volume
    if math.isnan(volume_db):
        raise CommandError(BAD_PARAMS, "volume_db is not a number")
    before = fader.value
    shown_before = fader.str_for_value(before)
    fader.value = value_for_db(fader, volume_db)
    live.record_value("Track '%s' fader: %s -> %s" % (
        track.name, shown_before, fader.str_for_value(fader.value)),
        fader, "value", before, label="the fader")
    return {
        "track_index": track_index,
        "name": track.name,
        "requested_db": None if math.isinf(volume_db) else volume_db,
        "volume_linear": fader.value,
        "display": fader.str_for_value(fader.value),
        "previous_display": shown_before,
    }


@command("set_track_mute", zone=REVERSIBLE, summary="Mute or unmute a track",
         params=[Int("track_index"), Bool("mute")])
def set_track_mute(live, track_index, mute):
    track = live.track(track_index)
    before = bool(track.mute)
    track.mute = mute
    live.record_value("Track '%s' mute: %s -> %s" % (
        track.name, "on" if before else "off", "on" if track.mute else "off"),
        track, "mute", before)
    return {"track_index": track_index, "name": track.name, "mute": bool(track.mute)}


@command("set_track_color", zone=REVERSIBLE,
         summary="Colour a track: palette index 0..69, or a 24-bit RGB value",
         params=[Int("track_index"), Int("color_index", None), Int("color_rgb", None)])
def set_track_color(live, track_index, color_index, color_rgb):
    track = live.track(track_index)
    before = track.color_index
    if color_rgb is None and color_index is not None and color_index >= _PALETTE_SIZE:
        # Older callers pass RGB through the index parameter.
        color_rgb, color_index = color_index, None
    if color_rgb is not None:
        if not 0 <= color_rgb <= 0xFFFFFF:
            raise CommandError(BAD_PARAMS, "color_rgb must be within 0x000000..0xFFFFFF")
        track.color = color_rgb  # Live snaps to the nearest palette colour
    elif color_index is not None:
        if color_index < 0:
            raise CommandError(BAD_PARAMS, "color_index must be within 0..69")
        track.color_index = color_index
    else:
        raise CommandError(BAD_PARAMS, "give color_index or color_rgb")
    live.record_value("Track '%s' colour: %s -> %s" % (track.name, before, track.color_index),
                      track, "color_index", before, label="the colour")
    return {
        "track_index": track_index,
        "name": track.name,
        "color_index": peek(track, "color_index"),
        "color_rgb": peek(track, "color"),
    }


@command("set_track_send", zone=REVERSIBLE,
         summary="Set a send amount (0..1) from a track to a return track",
         params=[Int("track_index"), Int("send_index"), Float("value")])
def set_track_send(live, track_index, send_index, value):
    track = live.track(track_index)
    send = pick(track.mixer_device.sends, send_index, "send")
    before = send.value
    send.value = max(float(send.min), min(float(send.max), value))
    live.record_value("Track '%s' send %d: %s -> %s" % (
        track.name, send_index, send.str_for_value(before), send.str_for_value(send.value)),
        send, "value", before, label="the send")
    return {
        "track": track.name,
        "send_index": send_index,
        "value": send.value,
        "display": send.str_for_value(send.value),
    }


@command("get_return_tracks", zone=READ, summary="Return tracks with fader state")
def get_return_tracks(live):
    rows = []
    for index, track in enumerate(live.song.return_tracks):
        fader = track.mixer_device.volume
        rows.append({
            "index": index,
            "name": track.name,
            "volume": fader.value,
            "volume_db": _fader_db(fader),
            "mute": bool(peek(track, "mute", False)),
            "devices": [device.name for device in track.devices],
        })
    return {"returns": rows}


@command("set_return_volume", zone=REVERSIBLE,
         summary="Set a return track fader (raw 0..1, 0.85 = 0 dB)",
         params=[Int("index"), Float("volume")])
def set_return_volume(live, index, volume):
    track = live.return_track(index)
    fader = track.mixer_device.volume
    if not float(fader.min) <= volume <= float(fader.max):
        raise CommandError(BAD_PARAMS, "volume must be within %s..%s" % (fader.min, fader.max))
    before = fader.value
    fader.value = volume
    live.record_value("Return '%s' fader: %s -> %s" % (
        track.name, fader.str_for_value(before), fader.str_for_value(fader.value)),
        fader, "value", before, label="the fader")
    return {"index": index, "name": track.name, "volume": fader.value,
            "display": fader.str_for_value(fader.value)}


@command("select_tracks", zone=READ,
         summary="Select a track in Live (multi-selection where Live allows it)",
         params=[Items("track_indices")])
def select_tracks(live, track_indices):
    if not track_indices:
        raise CommandError(BAD_PARAMS, "track_indices is empty")
    try:
        indices = sorted(set(int(i) for i in track_indices))
    except (TypeError, ValueError):
        raise CommandError(BAD_PARAMS, "track_indices must be integers")
    chosen = [live.track(i) for i in indices]
    view = live.song.view
    view.selected_track = chosen[0]
    # Live's API has a single selected track. Report honestly what happened.
    return {
        "selected_index": indices[0],
        "selected_name": chosen[0].name,
        "requested_indices": indices,
        "track_names": [t.name for t in chosen],
        "multi_selection": False,
        "hint": "Live's API selects one track only. To group several, "
                "shift-click the others in Live and press Ctrl+G."
                if len(indices) > 1 else "",
    }


@command("group_tracks", zone=REVERSIBLE, journal=False,
         summary="Prepare grouping: check the tracks and select the first one",
         params=[Items("track_indices")])
def group_tracks(live, track_indices):
    """Live's API has no grouping call. This command validates the request
    and selects the first track in the Session view; the caller then extends
    the selection and presses Ctrl+G (the MCP tool does that)."""
    try:
        indices = sorted(set(int(i) for i in track_indices))
    except (TypeError, ValueError):
        raise CommandError(BAD_PARAMS, "track_indices must be integers")
    if len(indices) < 2:
        raise CommandError(BAD_PARAMS, "give at least two track indices")
    chosen = [live.track(index) for index in indices]
    if indices != list(range(indices[0], indices[-1] + 1)):
        raise CommandError(BAD_PARAMS, "tracks to group must be next to each other")
    view = live.song.view
    view.selected_track = chosen[0]
    live.app.view.show_view("Session")
    live.app.view.focus_view("Session")
    # Put the Session cursor on the first slot of that track: from there one
    # "arrow up" reaches the track title, where Shift+arrows select tracks.
    if len(live.song.scenes):
        view.selected_scene = live.song.scenes[0]
    slots = chosen[0].clip_slots
    if len(slots):
        view.highlighted_clip_slot = slots[0]
    return {
        "prepared": True,
        "grouped": False,
        "first_index": indices[0],
        "count": len(indices),
        "track_names": [track.name for track in chosen],
        "track_count": len(live.song.tracks),
    }


@command("freeze_track", zone=READ,
         summary="Report freeze state (Live's API cannot freeze or unfreeze)",
         params=[Int("track_index"), Bool("freeze", True)])
def freeze_track(live, track_index, freeze):
    track = live.track(track_index)
    frozen = bool(peek(track, "is_frozen", False))
    return {
        "track_index": track_index,
        "name": track.name,
        "is_frozen": frozen,
        "can_be_frozen": bool(peek(track, "can_be_frozen", False)),
        "requested": freeze,
        "changed": False,
        "note": "Live's API has no freeze call. Use 'Freeze Track' in the track's "
                "context menu in Live." if frozen != freeze else "already in that state",
    }


@command("get_master_levels", zone=READ,
         summary="Momentary output meter of the master track")
def get_master_levels(live):
    master = live.song.master_track
    left = float(master.output_meter_left)
    right = float(master.output_meter_right)

    def to_db(level):
        return round(20.0 * math.log10(level), 1) if level > 1e-9 else None

    return {
        "meter_left": round(left, 4),
        "meter_right": round(right, 4),
        "peak_db": to_db(max(left, right)),
        "mean_db": to_db((left + right) / 2.0),
        "is_playing": bool(live.song.is_playing),
        "note": "Peak meter snapshot, not a loudness measurement.",
    }
