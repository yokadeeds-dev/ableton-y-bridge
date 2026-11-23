# Copyright (C) 2026 Yoka
# SPDX-License-Identifier: AGPL-3.0-only
"""Warp marker primitives on top of whatever the running Live version offers.

A warp marker pins a point of the sample (``sample_time``, seconds) to a
point on the timeline (``beat_time``, beats, relative to the clip).
"""

from .errors import NOT_FOUND, UNSUPPORTED, CommandError
from .liveaccess import peek

_SAME_BEAT = 1e-4


def read(clip):
    """All markers of an audio clip, ordered by beat time."""
    raw = peek(clip, "warp_markers")
    if raw is None:
        raise CommandError(UNSUPPORTED, "this Live version does not expose warp markers")
    markers = [
        {"beat_time": float(m.beat_time), "sample_time": float(m.sample_time)} for m in raw
    ]
    markers.sort(key=lambda m: m["beat_time"])
    return markers


def nearest(markers, beat_time):
    """(index, marker, distance) of the marker closest to ``beat_time``."""
    if not markers:
        raise CommandError(NOT_FOUND, "the clip has no warp markers")
    index = min(range(len(markers)), key=lambda i: abs(markers[i]["beat_time"] - beat_time))
    return index, markers[index], abs(markers[index]["beat_time"] - beat_time)


def at_beat(markers, beat_time):
    for marker in markers:
        if abs(marker["beat_time"] - beat_time) <= _SAME_BEAT:
            return marker
    return None


def capabilities(clip, live_module):
    """Which marker calls exist here (for diagnostics)."""
    names = ("add_warp_marker", "move_warp_marker", "remove_warp_marker",
             "set_warp_marker", "insert_warp_marker")
    found = dict((name, callable(peek(clip, name))) for name in names)
    found["WarpMarker_class"] = hasattr(live_module.Clip, "WarpMarker")
    return found


def add(clip, beat_time, sample_time, live_module):
    """Create a marker pinning ``sample_time`` to ``beat_time``."""
    adder = peek(clip, "add_warp_marker")
    maker = getattr(live_module.Clip, "WarpMarker", None)
    if callable(adder) and maker is not None:
        try:
            marker = maker(sample_time=float(sample_time), beat_time=float(beat_time))
        except TypeError:
            marker = maker(float(sample_time), float(beat_time))
        adder(marker)
        return "add_warp_marker"
    for name in ("set_warp_marker", "insert_warp_marker"):
        legacy = peek(clip, name)
        if callable(legacy):
            legacy(float(beat_time), float(sample_time))
            return name
    raise CommandError(
        UNSUPPORTED,
        "this Live version offers no call to create warp markers; "
        "write them into the .als file with als_warp_write instead",
    )


def move(clip, beat_time, new_beat_time):
    """Slide the marker at ``beat_time`` along the timeline."""
    mover = peek(clip, "move_warp_marker")
    if not callable(mover):
        raise CommandError(UNSUPPORTED, "this Live version cannot move warp markers")
    mover(float(beat_time), float(new_beat_time) - float(beat_time))


def remove(clip, beat_time):
    remover = peek(clip, "remove_warp_marker")
    if not callable(remover):
        raise CommandError(UNSUPPORTED, "this Live version cannot remove warp markers")
    remover(float(beat_time))


def place(clip, beat_time, sample_time, live_module):
    """Make sure ``sample_time`` sits at ``beat_time``.

    If a marker already holds this sample position it is moved, if one
    already sits on this beat with another sample position it is replaced,
    otherwise a new marker is created. Returns what was done.
    """
    existing = read(clip)
    for marker in existing:
        if abs(marker["sample_time"] - sample_time) <= 1e-6:
            if abs(marker["beat_time"] - beat_time) <= _SAME_BEAT:
                return "unchanged"
            move(clip, marker["beat_time"], beat_time)
            return "moved"
    occupant = at_beat(existing, beat_time)
    if occupant is not None:
        remove(clip, occupant["beat_time"])
        add(clip, beat_time, sample_time, live_module)
        return "replaced"
    add(clip, beat_time, sample_time, live_module)
    return "added"


def pin(clip, marker, live_module):
    """Turn an implicit position into a real marker so neighbours hold still."""
    if at_beat(read(clip), marker["beat_time"]) is not None:
        return False
    add(clip, marker["beat_time"], marker["sample_time"], live_module)
    return True


def to_grid(beat_time, grid):
    return round(beat_time / grid) * grid


def same_markers(left, right):
    if len(left) != len(right):
        return False
    return all(abs(a["beat_time"] - b["beat_time"]) <= _SAME_BEAT
               and abs(a["sample_time"] - b["sample_time"]) <= 1e-5
               for a, b in zip(left, right))


def restore(clip, wanted, live_module):
    """Bring the clip's markers back to the list ``wanted`` as far as Live allows."""
    def held_in(markers, marker):
        return any(abs(m["beat_time"] - marker["beat_time"]) <= _SAME_BEAT
                   and abs(m["sample_time"] - marker["sample_time"]) <= 1e-5 for m in markers)

    for marker in read(clip):
        if not held_in(wanted, marker):
            try:
                remove(clip, marker["beat_time"])
            except Exception:
                pass  # Live keeps the markers it needs at the ends
    present = read(clip)
    for marker in wanted:
        if not held_in(present, marker):
            add(clip, marker["beat_time"], marker["sample_time"], live_module)
    final = read(clip)
    return {"markers": len(final), "exact": same_markers(final, wanted)}
