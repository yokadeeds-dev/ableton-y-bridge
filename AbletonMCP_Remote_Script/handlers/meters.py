# Copyright (C) 2026 Yoka
# SPDX-License-Identifier: AGPL-3.0-only
"""Output meters of every track, return track and the master, sampled over a window.

Live's API exposes the same meters Live draws in the mixer (``output_meter_left``
and ``output_meter_right``, 0.0 to 1.0). One reading is a single moment, so the
command samples them on every display tick (five to ten times a second) for a
short window and reports the highest and the average reading per track,
converted to approximate dBFS with a calibration measured in Live (below).
Good for comparing tracks and spotting overloads; not a loudness measurement.
"""

import time

from ..liveaccess import peek
from ..registry import READ, Bool, Float, Later, command

MAX_SECONDS = 10.0

# Live's meter scale is linear in dB. Measured against the Y Meter device in
# Live 12.3.6 (fader steps from 0 to -40 dB, peaks from -13 to -53 dBFS):
# meter = 0.01292 * dB + 0.9043, within about 2 dB. 0 dBFS is a reading of
# about 0.90; 1.0 is about +7 dB, the top of Live's meters.
METER_PER_DB = 0.01292
METER_AT_0DB = 0.9043
METER_FLOOR = 0.01  # below this (about -69 dB) the meter counts as silent


def meter_to_db(value):
    """Approximate dBFS of a Live meter reading, or None for silence."""
    value = float(value)
    if value < METER_FLOOR:
        return None
    return round((value - METER_AT_0DB) / METER_PER_DB, 1)
MAX_TICKS_PER_SECOND = 20  # safety cap; Live's display tick runs at about 5 to 10 per second


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

    def sample():
        if song.is_playing:
            was_playing[0] = True
        for (_kind, _index, track), stat in zip(targets, stats):
            if not peek(track, "has_audio_output", True):
                continue
            left = peek(track, "output_meter_left", None)
            right = peek(track, "output_meter_right", None)
            if left is None or right is None:
                continue
            value = max(float(left), float(right))
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
            "note": "Live meter readings (0..1); dB values are approximate (about +-2 dB), "
                    "post-fader, mean over readings, not loudness.",
        }

    cap = max(1, int(seconds * MAX_TICKS_PER_SECOND))
    taken = [0]

    def step():
        sample()
        taken[0] += 1
        if time.time() - started >= seconds or taken[0] >= cap:
            return finish()
        return Later(step, 1)

    return step()
