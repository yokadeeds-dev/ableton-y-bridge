# Copyright (C) 2026 Yoka
# SPDX-License-Identifier: AGPL-3.0-only
"""Output meters of every track, return track and the master, sampled over a window.

Live's API exposes the meters Live draws in the mixer. ``output_meter_level``
is the louder of ``output_meter_left`` and ``output_meter_right`` and holds a
peak for about a second; left and right do not hold. The command reads
``output_meter_level`` (falling back to the louder of left and right) on every
display tick, about ten times a second, for a short window and reports the
highest and the average reading per track in dBFS. Good for comparing tracks
and spotting overloads; not a loudness measurement.
"""

import time

from ..liveaccess import peek
from ..registry import READ, Bool, Float, Later, command

MAX_SECONDS = 10.0

# Live's meter scale is linear in dB: dBFS = 76 * meter - 70 (the formula
# Faderhand uses). Checked in Live 12.3.6 with 1 kHz sine files of known peak
# level from 0 to -60 dBFS: every step within 0.01 dB, for output_meter_level,
# left and right alike (conformance repository, calibration report 2026-11-23).
# An earlier calibration against the Y Meter device was 0.2 to 1.3 dB off.
DB_PER_METER = 76.0
DB_AT_METER_ZERO = -70.0
METER_AT_0DB = -DB_AT_METER_ZERO / DB_PER_METER  # 0.921
METER_FLOOR = 0.01  # below this (about -69 dB) the meter counts as silent


def meter_to_db(value):
    """dBFS of a Live meter reading, or None for silence."""
    value = float(value)
    if value < METER_FLOOR:
        return None
    return round(DB_PER_METER * value + DB_AT_METER_ZERO, 1)


def meter_of(track):
    """The track's meter reading: output_meter_level, else the louder channel."""
    level = peek(track, "output_meter_level", None)
    if level is not None:
        return float(level)
    left = peek(track, "output_meter_left", None)
    right = peek(track, "output_meter_right", None)
    if left is None or right is None:
        return None
    return max(float(left), float(right))


_KEY = "meter_sessions"
MIN_GAP_S = 0.05  # two readings closer than this count as one


def sample_tick(live):
    """Ticker: one reading for every running measurement, on every display tick."""
    sessions = live.state.get(_KEY) or {}
    for session in list(sessions.values()):
        session()
    if not sessions:
        live.state.get("tickers", {}).pop(_KEY, None)


def _targets(song, include_returns):
    found = [("track", index, track) for index, track in enumerate(song.tracks)]
    if include_returns:
        found += [("return", index, track) for index, track in enumerate(song.return_tracks)]
    found.append(("master", 0, song.master_track))
    return found


@command("get_track_meters", zone=READ,
         summary="Sample the output meters of all tracks, return tracks and the master",
         params=[Float("seconds", 2.0), Bool("include_returns", True)],
         timeout=15.0)
def get_track_meters(live, seconds, include_returns):
    seconds = min(max(float(seconds), 0.0), MAX_SECONDS)
    song = live.song
    targets = _targets(song, include_returns)
    stats = [{"peak": 0.0, "sum": 0.0, "n": 0, "over": 0} for _ in targets]
    started = time.time()
    was_playing = [bool(song.is_playing)]
    taken = [0]
    last = [0.0]

    def sample():
        now = time.time()
        if now - last[0] < MIN_GAP_S:
            return
        last[0] = now
        taken[0] += 1
        if song.is_playing:
            was_playing[0] = True
        for (_kind, _index, track), stat in zip(targets, stats):
            if not peek(track, "has_audio_output", True):
                continue
            value = meter_of(track)
            if value is None:
                continue
            stat["peak"] = max(stat["peak"], value)
            stat["sum"] += value
            stat["n"] += 1
            if value >= METER_AT_0DB:
                stat["over"] += 1

    def finish():
        rows = []
        for (kind, index, track), stat in zip(targets, stats):
            row = {"kind": kind, "index": index, "name": str(peek(track, "name", ""))}
            if stat["n"] == 0:
                row["audio_output"] = False
            else:
                mean = stat["sum"] / stat["n"]
                row.update({
                    "audio_output": True,
                    "meter_peak": round(stat["peak"], 4),
                    "meter_mean": round(mean, 4),
                    "peak_db": meter_to_db(stat["peak"]),
                    "mean_db": meter_to_db(mean),
                    "over_0db": stat["over"],
                })
            rows.append(row)
        return {
            "seconds": round(time.time() - started, 2),
            "samples": taken[0],
            "playing": was_playing[0],
            "tracks": rows,
            "note": "Live meter readings (0..1, output_meter_level, holds peaks about 1 s); dBFS = 76 * meter - 70, "
                    "post-fader, mean over readings, not loudness.",
        }

    # The readings come from a ticker that runs on every display tick (about
    # ten a second); a deferred result only gets a turn every second tick.
    sessions = live.state.setdefault(_KEY, {})
    key = "%d-%f" % (id(stats), started)
    sessions[key] = sample
    live.state.setdefault("tickers", {})[_KEY] = ("handlers.meters", "sample_tick")
    sample()

    def check():
        if time.time() - started >= seconds:
            sessions.pop(key, None)
            sample()
            return finish()
        return Later(check, 1)

    if seconds <= 0:
        sessions.pop(key, None)
        return finish()
    return Later(check, 1)
