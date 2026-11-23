# Copyright (C) 2026 Yoka
# SPDX-License-Identifier: AGPL-3.0-only
"""Shared objects of the MCP server: the FastMCP app, the link to Live, the
analyzer feed and the ``tool`` decorator all tool modules use."""

from __future__ import annotations

import functools
import json
import math
import logging
import os
from contextlib import asynccontextmanager
from typing import Callable, Dict, List

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

from .analyzer_feed import AnalyzerFeed
from .coerce import to_bool
from .link import LiveError, LiveLink

log = logging.getLogger("ableton_mcp")

READ = "read"
REVERSIBLE = "reversible"
DESTRUCTIVE = "destructive"
_ZONE_ORDER = (READ, REVERSIBLE, DESTRUCTIVE)

live = LiveLink()
analyzer = AnalyzerFeed()

# name -> {"zone": ..., "summary": ...}; filled by @tool, read by bridge_status
TOOLS: Dict[str, dict] = {}


def strict_json(value):
    """Replace inf and nan (a fader at -inf dB, for example) with None.

    JSON has no infinity; json.dumps would write -Infinity, which strict
    parsers reject. None becomes null; display strings still say '-inf dB'.
    """
    if isinstance(value, float) and (math.isinf(value) or math.isnan(value)):
        return None
    if isinstance(value, dict):
        return {key: strict_json(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [strict_json(item) for item in value]
    return value

INSTRUCTIONS = (
    "Tools to control Ableton Live through a Remote Script. All track, clip, scene and "
    "device indices are 0-based. Positions and lengths are in beats unless stated. "
    "Changes act on the open Live Set at once; most can be undone with `undo`. "
    "Prefer one bulk call (replace_notes_in_clip, set_warp_markers_batch) over many "
    "single calls. Tools that write .als files need the project reloaded in Live "
    "afterwards. Safety: every change gets a journal number (#n) shown in the answer; "
    "undo_ai_change(n) takes back exactly that step, list_ai_changes shows the journal. "
    "Destructive tools (deleting devices or locators, saving, writing .als files) only "
    "run with confirm=true: ask the user first, never set it on your own initiative."
)


def max_zone() -> str:
    """Highest zone this server may use (environment ABLETON_MCP_MAX_ZONE)."""
    chosen = os.environ.get("ABLETON_MCP_MAX_ZONE", DESTRUCTIVE).strip().lower()
    return chosen if chosen in _ZONE_ORDER else DESTRUCTIVE


def note_outside_change(text: str, undo: str = "none") -> None:
    """Journal a change this server made outside the bridge (a file, a shortcut).

    Best effort: when Live is not running there is no journal to write to.
    """
    try:
        live.call("note_change", text=text, undo=undo)
    except LiveError:
        pass


@asynccontextmanager
async def _lifespan(_server: FastMCP):
    analyzer.start()
    try:
        yield {}
    finally:
        analyzer.stop()
        live.close()


mcp = FastMCP("AbletonMCP", instructions=INSTRUCTIONS, lifespan=_lifespan)


def tool(zone: str = READ, unless: Callable = None) -> Callable:
    """Register a function as an MCP tool.

    The wrapper

    * refuses tools above the allowed zone (ABLETON_MCP_MAX_ZONE),
    * lets a destructive tool run only with ``confirm=true`` (``unless`` may
      exempt harmless uses such as a dry run; it gets the keyword arguments),
    * appends the journal numbers of the changes the call made,
    * turns every failure into a one-line text answer.
    """
    if zone not in (READ, REVERSIBLE, DESTRUCTIVE):
        raise ValueError(f"unknown zone {zone!r}")

    def register(function: Callable) -> Callable:
        name = function.__name__

        @functools.wraps(function)
        def guarded(*args, **kwargs):
            harmless = unless is not None and unless(kwargs)
            if not harmless and _ZONE_ORDER.index(zone) > _ZONE_ORDER.index(max_zone()):
                return (f"Not executed [zone_not_allowed]: {name} is a {zone} tool and this "
                        f"server is limited to '{max_zone()}' (ABLETON_MCP_MAX_ZONE). "
                        "Ask the user before going on.")
            confirmed = False
            if zone == DESTRUCTIVE and not harmless:
                try:
                    confirmed = to_bool(kwargs.get("confirm", False), "confirm")
                except ValueError:
                    confirmed = False
                if not confirmed:
                    return (f"Not executed [needs_confirmation]: {name} is destructive "
                            f"({summary}). Ask the user; if they agree, call it again with "
                            "confirm=true.")
            live.confirmed, live.journal = confirmed, []
            try:
                answer = _run(function, name, args, kwargs)
                steps = list(live.journal)
            finally:
                live.confirmed, live.journal = False, None
            if steps:
                if isinstance(answer, dict) and "journal" not in answer:
                    answer["journal"] = steps
                elif isinstance(answer, str) and not answer.startswith("Error"):
                    answer += "\nJournal: " + "; ".join(
                        f"#{step['n']} {step['text']}" for step in steps[:8])
                    if len(steps) > 8:
                        answer += f"; ... {len(steps) - 8} more"
            if isinstance(answer, (dict, list)):
                return json.dumps(strict_json(answer), indent=2, ensure_ascii=False,
                                  default=str, allow_nan=False)
            return answer

        def _run(function, name, args, kwargs):
            try:
                return function(*args, **kwargs)
            except LiveError as problem:
                extra = ""
                if problem.details:
                    extra = " | " + json.dumps(problem.details, ensure_ascii=False, default=str)
                return f"Error in {name} [{problem.code}]: {problem}{extra}"
            except (ValueError, TypeError, KeyError) as problem:
                return f"Error in {name} [bad_input]: {problem}"
            except Exception as problem:  # last line of defence, with traceback in the log
                log.exception("tool %s failed", name)
                return f"Error in {name} [internal]: {type(problem).__name__}: {problem}"

        summary = (function.__doc__ or "").strip().split("\n", 1)[0]
        TOOLS[name] = {"zone": zone, "summary": summary}
        mcp.tool(annotations=ToolAnnotations(
            readOnlyHint=zone == READ,
            destructiveHint=zone == DESTRUCTIVE,
            openWorldHint=False,
        ))(guarded)
        return guarded

    return register


def lines(*parts: str) -> str:
    return "\n".join(part for part in parts if part is not None)


def bullet_list(items: List[str], empty: str = "none") -> str:
    return ", ".join(items) if items else empty
