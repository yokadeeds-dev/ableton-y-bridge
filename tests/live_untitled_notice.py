# Copyright (C) 2026 Yoka
# SPDX-License-Identifier: AGPL-3.0-only
"""Checks D18 against a running Ableton Live: the notice in an untitled Set.

Reads Song.file_path through get_session_info (set_path), then mutes and
unmutes one track twice and looks for the notice in the answers. In an
untitled Set the first change carries it and the later ones do not; in a
saved Set none does. Every change is taken back through the journal at the
end, so the mute state is as before.

    python tests/live_untitled_notice.py --track 0 --expect untitled
    python tests/live_untitled_notice.py --track 0 --expect saved

Run the saved case first after a start of Live (the flag is cleared by a change
in a saved Set), or run it in a saved Set, then in a new one.
"""

from __future__ import annotations

import argparse
import datetime
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault("ABLETON_MCP_EDIT_RATE", "0")

from MCP_Server.link import LiveLink  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--track", type=int, required=True)
    parser.add_argument("--expect", choices=("untitled", "saved"), required=True)
    args = parser.parse_args()
    link = LiveLink()
    started = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    version = link.call("get_version")
    info = link.call("get_session_info")
    path = info.get("set_path")
    track = link.call("get_track_info", track_index=args.track)
    muted = bool(track.get("mute"))
    notices, steps = [], []
    try:
        for mute in (not muted, muted, not muted, muted):
            result = link.call("set_track_mute", track_index=args.track, mute=mute)
            notices.append(result.get("notice"))
            steps += [entry["n"] for entry in result.get("journal") or []]
    finally:
        for n in reversed(steps):
            link.call("undo_change", n=n)
        link.close()
    if args.expect == "untitled":
        passed = path == "" and bool(notices[0]) and not any(notices[1:])
    else:
        passed = bool(path) and not any(notices)
    print(f"## Notice in an untitled Set in Live (D18), {started}\n")
    print(f"Live {version.get('live_version')}, bridge "
          f"{version.get('bridge_version') or version.get('version', '?')}; "
          f"`python tests/live_untitled_notice.py --track {args.track} --expect {args.expect}`; "
          f"{len(steps)} step(s) taken back.\n")
    print("| Check | Verdict | Seen |\n|---|---|---|")
    seen = {"set_path": path, "notices": [bool(n) for n in notices],
            "first": (notices[0] or "")[:40]}
    print(f"| {args.expect} Set, 4 changes | {'pass' if passed else 'FAIL'} | `{seen}` |")
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
