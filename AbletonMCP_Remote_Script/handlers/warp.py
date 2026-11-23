# Copyright (C) 2026 Yoka
# SPDX-License-Identifier: AGPL-3.0-only
"""Warp markers of Arrangement audio clips, single and in bulk."""

from .. import warpops
from ..errors import BAD_PARAMS, CommandError
from ..registry import READ, REVERSIBLE, Float, Int, Items, Raw, command
from . import legacy


def record_markers(live, clip, before, text):
    """Journal a warp marker edit; undo puts the previous markers back."""
    after = warpops.read(clip)
    if warpops.same_markers(before, after):
        live.quiet()
        return
    module = live.live_module()

    def valid():
        try:
            current = warpops.read(clip)
        except Exception:
            return "the clip no longer exists"
        return None if warpops.same_markers(current, after) else (
            "the warp markers were changed since")

    def undo():
        return warpops.restore(clip, before, module)

    live.record(text, undo, valid)

WARP_MODES = {0: "Beats", 1: "Tones", 2: "Texture", 3: "Re-Pitch", 4: "Complex", 6: "Complex Pro"}


@command("get_warp_markers", zone=READ,
         summary="Warp markers of an Arrangement audio clip",
         params=[Int("track_index"), Int("clip_index")])
def get_warp_markers(live, track_index, clip_index):
    clip = live.arrangement_clip(track_index, clip_index, kind="audio")
    markers = warpops.read(clip)
    return {"track": track_index, "clip": clip_index, "clip_name": clip.name,
            "warping": bool(clip.warping), "count": len(markers), "warp_markers": markers}


@command("set_clip_warp_mode", zone=REVERSIBLE,
         summary="Switch warping on and choose the warp mode of an Arrangement clip",
         params=[Int("track_index"), Int("clip_index"), Int("mode", 4)])
def set_clip_warp_mode(live, track_index, clip_index, mode):
    clip = live.arrangement_clip(track_index, clip_index, kind="audio")
    allowed = [int(m) for m in getattr(clip, "available_warp_modes", WARP_MODES)]
    if mode == 5 and 5 not in allowed and 6 in allowed:
        mode = 6  # Complex Pro is 6 in Live's enumeration; 5 is REX
    if mode not in allowed:
        raise CommandError(BAD_PARAMS, "warp mode %d is not available for this clip" % mode,
                           available=dict((m, WARP_MODES.get(m, "?")) for m in allowed))
    before = (bool(clip.warping), int(clip.warp_mode))
    if not clip.warping:
        clip.warping = True
    clip.warp_mode = mode

    def valid():
        try:
            return None if int(clip.warp_mode) == mode else "the warp mode was changed since"
        except Exception:
            return "the clip no longer exists"

    def undo():
        clip.warp_mode = before[1]
        clip.warping = before[0]
        return {"restored": "warp mode"}

    live.record("Clip '%s' warp: %s%s -> %s" % (
        clip.name, WARP_MODES.get(before[1], before[1]), "" if before[0] else " (off)",
        WARP_MODES.get(mode, mode)), undo, valid)
    return {"track": track_index, "clip": clip_index, "warping": bool(clip.warping),
            "warp_mode": int(clip.warp_mode),
            "warp_mode_name": WARP_MODES.get(int(clip.warp_mode), "?")}


@command("set_warp_marker", zone=REVERSIBLE,
         summary="Pin a sample position (seconds) to a beat position",
         params=[Int("track_index"), Int("clip_index"), Float("beat_time"), Float("sample_time")])
def set_warp_marker(live, track_index, clip_index, beat_time, sample_time):
    clip = live.arrangement_clip(track_index, clip_index, kind="audio")
    before = warpops.read(clip)
    action = warpops.place(clip, beat_time, sample_time, live.live_module())
    record_markers(live, clip, before, "Clip '%s': warp marker %s (%.3f s at beat %.3f)"
                   % (clip.name, action, sample_time, beat_time))
    return {"track": track_index, "clip": clip_index, "beat_time": beat_time,
            "sample_time": sample_time, "action": action}


@command("set_warp_markers_batch", zone=REVERSIBLE,
         summary="Set several warp markers on one Arrangement clip",
         params=[Raw("track_index"), Raw("clip_index", 0), Items("markers", [])],
         timeout=30.0)
def set_warp_markers_batch(live, track_index, clip_index, markers):
    # Earlier versions of this bridge smuggled other commands through this
    # one by passing words instead of a track number. Those calls still work.
    if legacy.is_keyword(track_index):
        return legacy.route(live, str(track_index), clip_index, markers)
    try:
        track_number, clip_number = int(track_index), int(clip_index)
    except (TypeError, ValueError):
        raise CommandError(BAD_PARAMS, "track_index and clip_index must be integers")
    clip = live.arrangement_clip(track_number, clip_number, kind="audio")
    module = live.live_module()
    before = warpops.read(clip)
    done, errors = 0, []
    for marker in markers:
        try:
            beat = float(marker["beat_time"])
            sample = float(marker["sample_time"])
        except (KeyError, TypeError, ValueError):
            errors.append({"marker": marker, "error": "needs beat_time and sample_time"})
            continue
        try:
            warpops.place(clip, beat, sample, module)
            done += 1
        except Exception as problem:
            errors.append({"beat_time": beat, "error": str(problem)})
    record_markers(live, clip, before, "Clip '%s': set %d warp markers" % (clip.name, done))
    return {"markers_set": done, "errors": errors, "total": len(warpops.read(clip))}


@command("probe_warp_api", zone=READ,
         summary="Which warp marker calls this Live version has (diagnostic)",
         params=[Int("track_index"), Int("clip_index")])
def probe_warp_api(live, track_index, clip_index):
    clip = live.arrangement_clip(track_index, clip_index, kind="audio")
    return {
        "calls": warpops.capabilities(clip, live.live_module()),
        "warp_members": sorted(n for n in dir(clip) if "warp" in n.lower()),
    }
