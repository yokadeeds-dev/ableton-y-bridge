# Copyright (C) 2026 Yoka
# SPDX-License-Identifier: AGPL-3.0-only
"""Checks D16 and D17 against a running Ableton Live: track levels and a transport stop.

Live's output_meter_level holds the last value for about 3 s after a stop
(conformance M3). get_track_meters counts only readings while the transport
runs. This script places a sine file of known level on the Arrangement of one
audio track and

A. stops the transport 1.5 s into a 6 s window: the result must count only the
   readings before the stop (peak and mean at the file level, stopped readings
   counted apart; the old code also averaged the zeros after the hold);
B. measures right after a stop: playing false, all readings counted as stopped;
C. stops, waits 1 s, starts again at a silent place and takes single readings:
   reports whether Live drops the held peak at the start (the limit named in D16);
D. the same start, measured over 1 s: the held peak must be left out (D17,
   held_only);
E. 4 s after that stop, still silent: clean readings, no level.

The clip lies at beat 64 and the transport always starts at beat 0 (silence):
Live starts from where playback last started, and moving the position while
stopped does not change that, so the loud part is reached by a jump while
playing.

It talks to the Remote Script directly (two connections, one for the window,
one for the transport). The clip is removed again through the journal at the
end; tempo is not changed. Run against a throwaway Set.

    python tests/live_meter_stop.py --track 2 --conformance C:\\Tools\\ableton-mcp-conformance --work-dir <folder>
"""

from __future__ import annotations

import argparse
import datetime
import os
import sys
import threading
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault("ABLETON_MCP_EDIT_RATE", "0")

from MCP_Server.link import LiveLink  # noqa: E402

LEVEL_DB = -12.0
FILE_SECONDS = 12.0          # 24 beats at 120 BPM
CLIP_BEAT = 64.0             # the clip; beats 0 to 64 are silent


def row_of(result: dict, track: int) -> dict:
    return next(row for row in result["tracks"] if row["kind"] == "track" and row["index"] == track)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--track", type=int, required=True, help="an audio track, routed to Main")
    parser.add_argument("--conformance", required=True, help="checkout of the conformance repo")
    parser.add_argument("--work-dir", required=True, help="folder for the sine file")
    args = parser.parse_args()
    sys.path.insert(0, os.path.join(args.conformance, "conformance"))
    from calibrate import RATE, write_sine  # noqa: E402

    os.makedirs(args.work_dir, exist_ok=True)
    path = os.path.abspath(os.path.join(
        args.work_dir, f"sine_1k_{LEVEL_DB:+05.1f}dBFS_{RATE // 1000}k_{FILE_SECONDS:.0f}s.wav"))
    if not os.path.exists(path):
        write_sine(path, LEVEL_DB, FILE_SECONDS)

    meters, transport = LiveLink(), LiveLink()
    # A Session clip on the track would play over the Arrangement: the silent
    # place would not be silent (a first run on such a track was invalid).
    info = transport.call("get_track_info", track_index=args.track)
    busy = [slot["index"] for slot in info.get("clip_slots") or [] if slot.get("has_clip")]
    if busy or info.get("arrangement_clip_count"):
        print("track %d is not empty (Session clips in slots %s, %s Arrangement clips): "
              "use an empty audio track" % (args.track, busy, info.get("arrangement_clip_count")))
        return 1
    rows, failed = [], 0
    started = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    version = transport.call("get_version")

    def record(what, passed, seen):
        nonlocal failed
        verdict = "pass" if passed is True else ("FAIL" if passed is False else "measured")
        failed += passed is False
        rows.append((what, verdict, seen))

    def play_loud(settle):
        transport.call("stop_playback")
        transport.call("jump_to_time", time=0.0)
        transport.call("start_playback")
        transport.call("jump_to_time", time=CLIP_BEAT)
        time.sleep(settle)

    transport.journal = []
    made = transport.call("create_arrangement_audio_clips",
                          clips=[{"track": args.track, "file_path": path, "position": CLIP_BEAT}])
    steps = list(transport.journal)
    transport.journal = None
    if not made.get("succeeded"):
        print("could not place the clip:", made)
        return 1
    try:
        # A: stop 1.5 s into a 6 s window
        play_loud(2.5)
        stopper = threading.Timer(1.5, lambda: transport.call("stop_playback"))
        stopper.start()
        result = meters.call("get_track_meters", seconds=6.0, include_returns=False)
        stopper.join()
        mine = row_of(result, args.track)
        seen = {"playing": result["playing"], "samples": result["samples"],
                "stopped_samples": result.get("stopped_samples"),
                "peak_db": mine.get("peak_db"), "mean_db": mine.get("mean_db")}
        record("A: stop 1.5 s into a 6 s window", result["playing"] is True
               and (result.get("stopped_samples") or 0) >= 10 and result["samples"] >= 5
               and mine.get("peak_db") is not None and abs(mine["peak_db"] - LEVEL_DB) <= 0.2
               and mine.get("mean_db") is not None and abs(mine["mean_db"] - LEVEL_DB) <= 0.3,
               seen)

        # B: right after a stop
        play_loud(2.5)
        transport.call("stop_playback")
        result = meters.call("get_track_meters", seconds=1.0, include_returns=False)
        mine = row_of(result, args.track)
        record("B: 1 s window right after a stop", result["playing"] is False
               and result["samples"] == result.get("stopped_samples"),
               {"playing": result["playing"], "samples": result["samples"],
                "stopped_samples": result.get("stopped_samples"), "peak_db": mine.get("peak_db")})

        # C: restart 1 s after a stop at a silent place, single readings
        play_loud(2.5)
        transport.call("stop_playback")
        time.sleep(1.0)
        restart = transport.call("start_playback")
        t0 = time.time()
        timeline = []
        while time.time() - t0 < 4.0:
            reading = meters.call("get_track_meters", seconds=0, include_returns=False)
            timeline.append((round(time.time() - t0, 2), reading["playing"],
                             row_of(reading, args.track).get("peak_db")))
        beat = transport.call("get_session_info").get("song_time_beats")
        transport.call("stop_playback")
        loud = [t for t, playing, db in timeline if playing and db is not None]
        record("C: start 1 s after a stop, at a silent place (started at beat %.1f, "
               "after 4 s at %.1f; clip from %.0f)"
               % (restart.get("song_time_beats", -1), beat or -1, CLIP_BEAT), None,
               {"readings": len(timeline),
                "held peak seen while playing until s": loud[-1] if loud else None,
                "first readings": timeline[:6]})

        # D: as C, but a 1 s window right after the start (D17): the held peak is
        # left out, the result says held_only (only held readings there are) and
        # the readings more than HOLD_S after the stop are silent.
        play_loud(2.5)
        transport.call("stop_playback")
        time.sleep(1.0)
        transport.call("start_playback")
        result = meters.call("get_track_meters", seconds=1.0, include_returns=False)
        mine = row_of(result, args.track)
        record("D: 1 s window right after a start 1 s after a stop (D17)",
               result.get("held_only") is True and result["playing"] is True
               and (result.get("held_samples") or 0) >= 5,
               {"held_only": result.get("held_only"), "held_samples": result.get("held_samples"),
                "samples": result["samples"], "hold_s": result.get("hold_s"),
                "peak_db": mine.get("peak_db")})
        time.sleep(2.0)                      # now 4 s after the stop, still silent
        result = meters.call("get_track_meters", seconds=1.0, include_returns=False)
        mine = row_of(result, args.track)
        transport.call("stop_playback")
        record("E: 1 s window 4 s after that stop, still silent (D17)",
               result.get("held_only") is False and result["samples"] >= 5
               and mine.get("peak_db") is None,
               {"held_only": result.get("held_only"), "held_samples": result.get("held_samples"),
                "samples": result["samples"], "peak_db": mine.get("peak_db")})
    finally:
        transport.call("stop_playback")
        for step in reversed(steps):
            transport.call("undo_change", n=step["n"])
        meters.close()
        transport.close()

    print(f"## Track levels and transport stop in Live (D16, D17), {started}\n")
    print(f"Live {version.get('live_version')}, bridge "
          f"{version.get('bridge_version') or version.get('version', '?')}; "
          f"`python tests/live_meter_stop.py --track {args.track}`; sine {LEVEL_DB} dBFS on the "
          f"Arrangement of track {args.track}, removed again through the journal "
          f"({len(steps)} step(s) taken back). {len(rows)} checks, {failed} FAIL.\n")
    print("| Check | Verdict | Seen |\n|---|---|---|")
    for what, verdict, seen in rows:
        print(f"| {what} | {verdict} | `{seen}` |")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
