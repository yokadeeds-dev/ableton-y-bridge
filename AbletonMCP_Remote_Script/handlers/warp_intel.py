"""Warp marker operations that look at the neighbourhood of a marker.

Moving a single warp marker stretches the audio between it and its two
neighbours. Each operation here therefore works on the nearest marker to a
given beat and can first pin the neighbours ("anchor") so the change stays
local. One command, `warp_intel`, with a ``cmd`` field per operation.
"""

from .. import warpops
from ..errors import BAD_PARAMS, CommandError
from ..registry import REVERSIBLE, Int, Raw, command

_ON_GRID = 1e-4


def _number(spec, key, fallback=None):
    value = spec.get(key, fallback)
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        raise CommandError(BAD_PARAMS, "'%s' must be a number" % key)


def _neighbours(markers, index):
    before = markers[index - 1] if index > 0 else None
    after = markers[index + 1] if index + 1 < len(markers) else None
    return before, after


def _anchor(clip, markers, index, module):
    pinned = []
    for side, neighbour in zip(("previous", "next"), _neighbours(markers, index)):
        if neighbour is not None:
            warpops.pin(clip, neighbour, module)
            pinned.append({"side": side, "beat_time": neighbour["beat_time"]})
    return pinned


def _in_range(markers, spec):
    low = _number(spec, "from_beat", float("-inf"))
    high = _number(spec, "to_beat", float("inf"))
    return [(i, m) for i, m in enumerate(markers) if low <= m["beat_time"] <= high], (low, high)


def op_get_markers(clip, spec, module):
    selected, _span = _in_range(warpops.read(clip), spec)
    return {"count": len(selected), "markers": [m for _i, m in selected]}


def op_find_nearest(clip, spec, module):
    grid = _number(spec, "grid_size", 1.0)
    markers = warpops.read(clip)
    index, marker, distance = warpops.nearest(markers, _number(spec, "beat_time", 0.0))
    before, after = _neighbours(markers, index)
    on_grid = warpops.to_grid(marker["beat_time"], grid)
    return {
        "found": True,
        "index": index,
        "marker": marker,
        "distance_beats": round(distance, 6),
        "nearest_grid": on_grid,
        "grid_offset_beats": round(marker["beat_time"] - on_grid, 6),
        "prev_marker": before,
        "next_marker": after,
        "total_markers": len(markers),
    }


def op_drag_to_grid(clip, spec, module):
    grid = _number(spec, "grid_size", 1.0)
    limit = _number(spec, "max_shift_beats", 0.5)
    markers = warpops.read(clip)
    index, marker, _distance = warpops.nearest(markers, _number(spec, "beat_time", 0.0))
    target = warpops.to_grid(marker["beat_time"], grid)
    shift = target - marker["beat_time"]
    if abs(shift) < _ON_GRID:
        return {"action": "already_on_grid", "marker": marker}
    if abs(shift) > limit:
        raise CommandError(
            BAD_PARAMS,
            "marker at beat %.4f would move %.4f beats, more than max_shift_beats=%s"
            % (marker["beat_time"], shift, limit),
        )
    anchored = _anchor(clip, markers, index, module) if spec.get("anchor", True) else []
    warpops.move(clip, marker["beat_time"], target)
    return {
        "action": "moved",
        "from_beat": round(marker["beat_time"], 6),
        "to_beat": round(target, 6),
        "shift_beats": round(shift, 6),
        "sample_time": marker["sample_time"],
        "anchored": anchored,
        "grid_size": grid,
    }


def op_nudge(clip, spec, module):
    markers = warpops.read(clip)
    index, marker, _distance = warpops.nearest(markers, _number(spec, "beat_time", 0.0))
    anchored = _anchor(clip, markers, index, module) if spec.get("anchor", True) else []
    by_sample = (spec.get("mode") == "sample" or "offset_ms" in spec
                 or "offset_samples" in spec)
    new_beat, new_sample = marker["beat_time"], marker["sample_time"]
    if by_sample:
        if "offset_ms" in spec:
            seconds = _number(spec, "offset_ms") / 1000.0
        elif "offset_samples" in spec:
            seconds = _number(spec, "offset_samples") / _number(spec, "sample_rate", 48000.0)
        else:
            seconds = 0.0
        new_sample = marker["sample_time"] + seconds
        warpops.remove(clip, marker["beat_time"])
        warpops.add(clip, new_beat, new_sample, module)
    else:
        new_beat = marker["beat_time"] + _number(spec, "offset_beats", 0.0)
        warpops.move(clip, marker["beat_time"], new_beat)
    return {
        "mode": "sample" if by_sample else "beat",
        "from": marker,
        "to": {"beat_time": round(new_beat, 6), "sample_time": round(new_sample, 6)},
        "anchored": anchored,
    }


def op_quantize_region(clip, spec, module):
    grid = _number(spec, "grid_size", 1.0)
    strength = _number(spec, "strength", 1.0)
    limit = _number(spec, "max_shift_beats", 0.5)
    markers = warpops.read(clip)
    selected, span = _in_range(markers, spec)
    moved, skipped = [], 0
    for _index, marker in selected:
        shift = (warpops.to_grid(marker["beat_time"], grid) - marker["beat_time"]) * strength
        if abs(shift) < _ON_GRID or abs(shift) > limit:
            skipped += 1
            continue
        new_beat = marker["beat_time"] + shift
        try:
            warpops.move(clip, marker["beat_time"], new_beat)
        except Exception:
            skipped += 1  # Live refuses moves that would cross a neighbour
            continue
        moved.append({"beat_from": round(marker["beat_time"], 4),
                      "beat_to": round(new_beat, 4), "shift": round(shift, 4)})
    return {"moved": len(moved), "skipped": skipped, "grid_size": grid, "strength": strength,
            "region": [None if abs(v) == float("inf") else v for v in span],
            "details": moved[:20]}


def op_anchor_and_move(clip, spec, module):
    move_beat = _number(spec, "move_beat")
    new_beat = _number(spec, "new_beat")
    new_sample = _number(spec, "new_sample")
    if move_beat is None or (new_beat is None and new_sample is None):
        raise CommandError(BAD_PARAMS, "needs move_beat and new_beat and/or new_sample")
    markers = warpops.read(clip)
    anchored = []
    for beat in spec.get("anchor_beats") or []:
        _i, marker, _d = warpops.nearest(markers, float(beat))
        warpops.pin(clip, marker, module)
        anchored.append(round(marker["beat_time"], 4))
    _index, target, _distance = warpops.nearest(markers, move_beat)
    end_beat = target["beat_time"] if new_beat is None else new_beat
    if new_sample is None:
        warpops.move(clip, target["beat_time"], end_beat)
        end_sample = target["sample_time"]
    else:
        end_sample = new_sample
        warpops.remove(clip, target["beat_time"])
        warpops.add(clip, end_beat, end_sample, module)
    return {"anchored": anchored, "from": target,
            "to": {"beat_time": round(end_beat, 6), "sample_time": round(end_sample, 6)}}


def op_analyze_drift(clip, spec, module):
    grid = _number(spec, "grid_size", 1.0)
    selected, _span = _in_range(warpops.read(clip), spec)
    if not selected:
        return {"count": 0}
    rows = []
    for _index, marker in selected:
        on_grid = warpops.to_grid(marker["beat_time"], grid)
        rows.append({"beat": round(marker["beat_time"], 4), "grid": round(on_grid, 4),
                     "drift": round(marker["beat_time"] - on_grid, 6)})
    drifts = [row["drift"] for row in rows]
    worst = max(rows, key=lambda row: abs(row["drift"]))
    balance = sum(drifts)
    scale = max(abs(worst["drift"]), 0.01)
    half = 20
    chart = ["drift per marker (< early | > late)"]
    for row in rows[:30]:
        bars = int(round(row["drift"] / scale * half))
        lane = " " * half + ">" * bars if bars >= 0 else " " * (half + bars) + "<" * (-bars)
        chart.append("  b%8.2f |%s" % (row["beat"], lane))
    return {
        "count": len(rows),
        "avg_drift_beats": round(sum(abs(d) for d in drifts) / len(drifts), 6),
        "max_drift_beats": worst["drift"],
        "max_drift_at_beat": worst["beat"],
        "tendency": "late" if balance > 0 else ("early" if balance < 0 else "neutral"),
        "grid_size": grid,
        "markers": rows[:30],
        "ascii_chart": "\n".join(chart),
    }


OPERATIONS = {
    "get_markers": op_get_markers,
    "find_nearest": op_find_nearest,
    "drag_to_grid": op_drag_to_grid,
    "nudge": op_nudge,
    "quantize_region": op_quantize_region,
    "anchor_and_move": op_anchor_and_move,
    "analyze_drift": op_analyze_drift,
}


CHANGING = ("drag_to_grid", "nudge", "quantize_region", "anchor_and_move")


def run(live, track_index, clip_index, spec):
    """Execute one operation dict against one Arrangement audio clip."""
    if not isinstance(spec, dict):
        raise CommandError(BAD_PARAMS, "operation must be an object with a 'cmd' field")
    name = spec.get("cmd", "")
    module = live.live_module()
    if name == "multi_clip":
        return _multi_clip(live, spec)
    operation = OPERATIONS.get(name)
    if operation is None:
        raise CommandError(BAD_PARAMS, "unknown warp_intel cmd '%s'" % name,
                           available=sorted(OPERATIONS) + ["multi_clip"])
    clip = live.arrangement_clip(track_index, clip_index, kind="audio")
    before = warpops.read(clip)
    result = operation(clip, spec, module)
    result["cmd"] = name
    if name in CHANGING:
        from .warp import record_markers

        record_markers(live, clip, before, "Clip '%s': warp %s" % (clip.name, name))
    else:
        live.quiet()
    return result


def _multi_clip(live, spec):
    targets = spec.get("clips") or []
    inner = spec.get("operation")
    if not targets or not isinstance(inner, dict):
        raise CommandError(BAD_PARAMS, "multi_clip needs 'clips' and an 'operation' object")
    if inner.get("cmd") not in OPERATIONS:
        raise CommandError(BAD_PARAMS, "unsupported operation '%s'" % inner.get("cmd"))
    results = []
    for target in targets:
        row = {"track": target.get("track", 0), "clip": target.get("clip", 0)}
        try:
            row["result"] = run(live, int(row["track"]), int(row["clip"]), dict(inner))
        except Exception as problem:
            row["error"] = str(problem)
        results.append(row)
    failed = sum(1 for row in results if "error" in row)
    return {"cmd": "multi_clip", "operation": inner.get("cmd"), "total": len(results),
            "succeeded": len(results) - failed, "failed": failed, "results": results}


@command("warp_intel", zone=REVERSIBLE,
         summary="Neighbour-aware warp marker operation (see 'cmd' in operation)",
         params=[Int("track_index", 0), Int("clip_index", 0), Raw("operation")],
         timeout=30.0)
def warp_intel(live, track_index, clip_index, operation):
    return run(live, track_index, clip_index, operation)
