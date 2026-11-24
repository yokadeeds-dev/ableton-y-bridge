# Copyright (C) 2026 Yoka
# SPDX-License-Identifier: AGPL-3.0-only
"""Output meters of every track, return track and the master, sampled over a window.

Live's API exposes the meters Live draws in the mixer. ``output_meter_level``
is the louder of ``output_meter_left`` and ``output_meter_right`` and holds
peaks: after a transport stop it keeps the last value for 2.6 to 3.4 s while
left and right fall within 1.3 s (measured, conformance M3), and a start in
that time does not clear it. Readings taken while the transport is stopped
are therefore left out when it ran in the window (D16), and so are readings
within 3.5 s of the last stop (D17). The command reads
``output_meter_level`` (falling back to the louder of left and right) on every
display tick, about ten times a second, for a short window and reports the
highest and the average reading per track in dBFS. Good for comparing tracks
and spotting overloads; not a loudness measurement.
"""

import time

from ..liveaccess import peek
from ..registry import READ, Bool, Float, Later, command, ticker

MAX_SECONDS = 10.0
COMMAND_TIMEOUT_S = 15.0

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

# After a stop output_meter_level holds the last value for up to 3.4 s
# (conformance M3), also when the transport starts again in that time (a start
# 1 s after a stop still read the old peak 0.2 s later, silent from 1.5 s;
# docs/LIVE_TEST_NOTES.md). Readings closer than this to the last stop are
# left out even while the transport runs (D17).
HOLD_S = 3.5
_WATCH = "transport_watch"        # the ticker
_WATCH_STATE = "transport_state"  # what it remembers


def _watch(live, now):
    """Note the time of a stop; returns the time of the last stop seen, or None."""
    watch = live.state.setdefault(_WATCH_STATE, {"playing": None, "stopped_at": None})
    try:
        playing = bool(live.song.is_playing)
    except Exception:                 # e.g. while Live loads a Set: keep what we know
        return watch["stopped_at"]
    if watch["playing"] and not playing:
        watch["stopped_at"] = now
    watch["playing"] = playing
    return watch["stopped_at"]


@ticker(_WATCH)
def transport_tick(live):
    """Runs with the bridge: catches stops between measurements too."""
    _watch(live, time.time())


def sample_tick(live):
    """Ticker: one reading for every running measurement, on every display tick.

    A measurement whose command timed out never collects its result, so every
    session carries a deadline and is dropped after it; a session that fails
    is dropped alone instead of stopping the ticker for all of them.
    """
    sessions = live.state.get(_KEY) or {}
    now = time.time()
    for key, session in list(sessions.items()):
        sample, deadline = session if isinstance(session, tuple) else (session, None)
        if deadline is not None and now > deadline:
            sessions.pop(key, None)
            continue
        try:
            sample()
        except Exception as problem:
            sessions.pop(key, None)
            live.log("meter session %s dropped: %s" % (key, problem))
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
         timeout=COMMAND_TIMEOUT_S)
def get_track_meters(live, seconds, include_returns):
    seconds = min(max(float(seconds), 0.0), MAX_SECONDS)
    song = live.song
    targets = _targets(song, include_returns)
    # Readings while the transport runs are the result (D16), except those
    # within HOLD_S of the last stop (D17). Readings while it is stopped count
    # only if it never ran in the window: right after a stop
    # output_meter_level still holds the last peak for about 3 s (measured,
    # conformance results/2026-11-24-1112-meter-behavior-windows.md).
    # Preference: clean readings, else held ones, else stopped ones.
    stats_by = {kind: [{"peak": 0.0, "sum": 0.0, "n": 0, "over": 0} for _ in targets]
                for kind in ("clean", "held", "stopped")}
    started = time.time()
    taken = {"clean": 0, "held": 0, "stopped": 0}
    last = [0.0]

    def sample():
        now = time.time()
        if now - last[0] < MIN_GAP_S:
            return
        last[0] = now
        stopped_at = _watch(live, now)
        if not song.is_playing:
            kind = "stopped"
        elif stopped_at is not None and now - stopped_at < HOLD_S:
            kind = "held"
        else:
            kind = "clean"
        taken[kind] += 1
        for (_kind, _index, track), stat in zip(targets, stats_by[kind]):
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
        used = next(kind for kind in ("clean", "held", "stopped")
                    if taken[kind] or kind == "stopped")
        stats = stats_by[used]
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
            "samples": taken[used],
            "stopped_samples": taken["stopped"],
            "held_samples": taken["held"],
            "held_only": used == "held",
            "hold_s": HOLD_S,
            "playing": used != "stopped",
            "tracks": rows,
            "note": "Live meter readings (0..1, output_meter_level, holds peaks; after a stop it "
                    "keeps the last value for about 3 s, also if playback starts again); "
                    "dBFS = 76 * meter - 70, post-fader, mean over the readings while the "
                    "transport ran and more than %.1f s after the last stop (else over the "
                    "readings there are), not loudness." % HOLD_S,
        }

    # The readings come from a ticker that runs on every display tick (about
    # ten a second); a deferred result only gets a turn every second tick.
    sessions = live.state.setdefault(_KEY, {})
    key = "%d-%f" % (id(stats_by), started)
    # Kept until the result is collected, at the latest until the command's
    # timeout is over (then nobody will collect it).
    sessions[key] = (sample, started + seconds + COMMAND_TIMEOUT_S + 1.0)
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
