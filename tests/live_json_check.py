# Copyright (C) 2026 Yoka
# SPDX-License-Identifier: AGPL-3.0-only
"""Checks the JSON answers (D14, D15) against a running Ableton Live.

The MCP server runs as a child process and is spoken to over stdio, as an
assistant would. Every change is taken back with undo_ai_change right after
its check; the destructive check is only a refusal (no confirm). Run it
against a throwaway Set.

    python tests/live_json_check.py --track 2 --other 3
    python tests/live_json_check.py --track 2 --other 3 --levels-slot 0

--levels-slot fires the clip in that slot of --track and reads
get_track_levels(as_json=true) while it plays (the clip must make sound).
Prints a Markdown section for docs/LIVE_TEST_NOTES.md; exit code 1 on a failure.
"""

from __future__ import annotations

import argparse
import asyncio
import datetime
import json
import os
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class Check:
    def __init__(self, session: ClientSession):
        self.session = session
        self.rows = []

    async def call(self, tool: str, **arguments) -> str:
        reply = await self.session.call_tool(tool, arguments)
        return "".join(block.text for block in reply.content if hasattr(block, "text"))

    async def json(self, tool: str, **arguments) -> dict:
        text = await self.call(tool, as_json=True, **arguments)
        try:
            return json.loads(text)
        except ValueError:
            return {"_not_json": text}

    def record(self, what: str, passed: bool, seen) -> None:
        shown = json.dumps(seen, ensure_ascii=False) if not isinstance(seen, str) else seen
        shown = shown.replace("\n", " ").replace("|", "\\|")
        self.rows.append((what, "pass" if passed else "FAIL",
                          shown if len(shown) <= 160 else shown[:157] + "..."))

    async def undo(self, data: dict) -> None:
        for step in reversed(data.get("journal") or []):
            await self.call("undo_ai_change", number=step["n"])


async def run(args) -> Check:
    server = StdioServerParameters(command=sys.executable,
                                   args=[os.path.join(ROOT, "MCP_Server", "server.py")],
                                   env=dict(os.environ, ABLETON_MCP_LOG_LEVEL="WARNING"))
    async with stdio_client(server) as (reader, writer):
        async with ClientSession(reader, writer) as session:
            await session.initialize()
            check = Check(session)
            tools = (await session.list_tools()).tools
            writes = [t.name for t in tools if not t.annotations.readOnlyHint]
            with_switch = [t.name for t in tools if "as_json" in t.inputSchema["properties"]]
            check.record("schema: as_json on every write tool and get_track_levels",
                         sorted(with_switch) == sorted(writes + ["get_track_levels"]),
                         f"{len(writes)} write tools, {len(with_switch)} with as_json")
            track, other = args.track, args.other

            data = await check.json("set_track_volume", track_index=track, volume_db=-6)
            check.record("set_track_volume -6 dB", data.get("ok") is True
                         and data.get("ref") == f"track:{track}"
                         and (data.get("now") or {}).get("display") == "-6.0 dB"
                         and bool(data.get("journal")), {k: data.get(k) for k in
                                                         ("ok", "ref", "now", "journal")})
            await check.undo(data)

            data = await check.json("set_track_mute", track_index=other, mute=True)
            check.record("set_track_mute on", data.get("ok") is True
                         and data.get("ref") == f"track:{other}"
                         and (data.get("now") or {}).get("mute") is True,
                         {k: data.get(k) for k in ("ok", "ref", "now")})
            await check.undo(data)

            data = await check.json("set_return_track_volume", index=1, volume=0.5)
            check.record("set_return_track_volume", data.get("ok") is True
                         and data.get("ref") == "return:1" and "now" in data,
                         {k: data.get(k) for k in ("ok", "ref", "now")})
            await check.undo(data)

            data = await check.json("set_tempo", tempo=121)
            check.record("set_tempo (song-wide)", data.get("ok") is True
                         and data.get("ref") is None and "now" in data,
                         {k: data.get(k) for k in ("ok", "ref", "now")})
            await check.undo(data)

            data = await check.json("create_midi_track", index=-1)
            now = data.get("now") or {}
            check.record("create_midi_track: ref from Live", data.get("ok") is True
                         and data.get("ref") == f"track:{now.get('index')}",
                         {k: data.get(k) for k in ("ok", "ref", "now")})
            await check.undo(data)

            data = await check.json("set_track_volume", track_index=99, volume_db=-6)
            check.record("error: track 99", data.get("ok") is False and data.get("code")
                         and data.get("ref") == "track:99", data)

            data = await check.json("clear_locators")
            check.record("refusal: clear_locators without confirm",
                         data.get("ok") is False and data.get("code") == "needs_confirmation",
                         {k: data.get(k) for k in ("ok", "code")})

            text = await check.call("set_track_volume", track_index=track, volume_db=-3)
            check.record("text stays the default", text.startswith(f"Track {track} ")
                         and "\nJournal: #" in text, text)
            number = int(text.split("\nJournal: #", 1)[1].split(" ", 1)[0])
            await check.call("undo_ai_change", number=number)

            if args.levels_slot is not None:
                await check.call("fire_clip", track_index=track, clip_index=args.levels_slot)
                await asyncio.sleep(2.0)
                text = await check.call("get_track_levels", seconds=2.0, as_json=True)
                await check.call("stop_playback")
                try:
                    levels = json.loads(text)
                except ValueError:
                    levels = {}
                rows = {row.get("ref"): row for row in levels.get("tracks", [])}
                mine = rows.get(f"track:{track}", {})
                check.record("get_track_levels as_json while playing",
                             levels.get("readings", 0) >= 1 and "master" in rows
                             and isinstance(mine.get("peak_dbfs"), (int, float)),
                             {"readings": levels.get("readings"), f"track:{track}": mine,
                              "master": rows.get("master")})
            return check


def report(check: Check, started: str) -> str:
    failed = sum(1 for row in check.rows if row[1] != "pass")
    out = [f"## JSON answers in Live (D14, D15), {started}", "",
           f"`python tests/live_json_check.py`: {len(check.rows)} checks, "
           f"{len(check.rows) - failed} pass, {failed} FAIL.", "",
           "| Check | Verdict | Seen |", "|---|---|---|"]
    out += [f"| {what} | {verdict} | `{seen}` |" for what, verdict, seen in check.rows]
    return "\n".join(out) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--track", type=int, required=True, help="a regular track index")
    parser.add_argument("--other", type=int, required=True, help="another regular track")
    parser.add_argument("--levels-slot", type=int, default=None,
                        help="clip slot of --track to play for the level check")
    args = parser.parse_args()
    started = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    check = asyncio.run(run(args))
    print(report(check, started))
    sys.exit(1 if any(row[1] != "pass" for row in check.rows) else 0)


if __name__ == "__main__":
    main()
