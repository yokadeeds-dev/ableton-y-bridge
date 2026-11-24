# Copyright (C) 2026 Yoka
# SPDX-License-Identifier: AGPL-3.0-only
"""Shared objects of the MCP server: the FastMCP app, the link to Live, the
analyzer feed and the ``tool`` decorator all tool modules use."""

from __future__ import annotations

import functools
import inspect
import json
import math
import logging
import os
from contextlib import asynccontextmanager
from typing import Callable, Dict, List

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

from .analyzer_feed import AnalyzerFeed
from .coerce import BoolLike, to_bool, to_int, to_list
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
    "Destructive tools (deleting devices, clearing all locators, saving, writing .als files) only "
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


class _Failure:
    """A refused or failed call; becomes text or, with as_json, a JSON error."""

    def __init__(self, code: str, text: str, message: str, details=None):
        self.code, self.text, self.message, self.details = code, text, message, details


class NotDone(str):
    """Text answer of a write that did not happen although nothing failed.

    The text form is unchanged; with as_json it becomes ``ok: false`` with
    ``code``.
    """

    def __new__(cls, text: str, code: str):
        answer = super().__new__(cls, text)
        answer.code = code
        return answer


class ReadBack(str):
    """Text answer of a write that names its own read-back for as_json.

    For tools whose Live results are not the state afterwards (group_tracks
    prepares in Live, then checks with a look-up).
    """

    def __new__(cls, text: str, now: dict):
        answer = super().__new__(cls, text)
        answer.now = now
        return answer


def _flag(given: dict, key: str) -> bool:
    try:
        return to_bool(given.get(key, False), key)
    except ValueError:
        return False


def _index(value):
    try:
        return to_int(value, "index")
    except (ValueError, TypeError):
        return None


def _ref(kind: str, value):
    index = _index(value)
    return None if index is None else f"{kind}:{index}"


# write tools that act on a return track, with the argument holding its index
_RETURN_TOOLS = {"load_device_on_return": "return_index",
                 "set_return_device_parameter": "return_index",
                 "set_return_track_volume": "index"}


# write tools whose target track only Live knows: key of the result holding it
_RESULT_TRACK = {"create_midi_track": "index", "create_audio_track": "index",
                 "group_tracks": "first_index"}


def write_target(name: str, given: dict, results: List[dict] = ()) -> dict:
    """Target of a write, in the forms of Spec § 2.

    ``given`` holds all arguments including defaults; ``results`` are the
    Live results of the call. ``ref`` is ``track:N``, ``return:N``,
    ``master`` or None (song-wide writes such as tempo, transport, locators
    or files); clip, device and scene numbers are added where the tool takes
    them, the grouped tracks as ``tracks``.
    """
    if given.get("als_path"):  # the tool edits a saved Set on disk, not the open one
        return {"ref": None, "file": str(given["als_path"])}
    ref = None
    if name in _RESULT_TRACK:
        key = _RESULT_TRACK[name]
        found = next((result[key] for result in results if key in result), None)
        if found is not None:
            ref = _ref("track", found)
    elif (name == "load_device_on_master" or _flag(given, "use_master")
            or _flag(given, "use_master_target")):
        ref = "master"
    elif _flag(given, "use_return"):
        ref = _ref("return", given.get("return_index", 0))
    elif _flag(given, "use_return_target"):
        ref = _ref("return", given.get("return_target_index", 0))
    elif name in _RETURN_TOOLS:
        ref = _ref("return", given.get(_RETURN_TOOLS[name], 0))
    else:
        for key in ("track_index", "target_track_index"):
            if given.get(key) is not None:
                index = given[key]
                ref = ("master" if str(index).strip().lower() == "master"
                       else _ref("track", index))
                break
    target = {"ref": ref}
    for key, field in (("clip_index", "clip"), ("device_index", "device"),
                       ("scene_index", "scene")):
        if given.get(key) is not None:
            target[field] = _index(given[key])
    if name == "group_tracks":
        try:
            target["tracks"] = [_ref("track", i)
                                for i in to_list(given.get("track_indices"), "track_indices")]
        except (ValueError, TypeError):
            pass
    return target


def _json(value) -> str:
    return json.dumps(strict_json(value), indent=2, ensure_ascii=False,
                      default=str, allow_nan=False)


def _without_journal(value):
    """A Live result as read-back: without the journal entries and the notice."""
    if isinstance(value, dict):
        return {key: item for key, item in value.items() if key not in ("journal", "notice")}
    if isinstance(value, list):
        return [_without_journal(item) for item in value]
    return value


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
    * turns every failure into a one-line text answer,
    * gives every write tool an ``as_json`` switch (Spec § 4, D15): the answer
      is then JSON with ``ok``, the target ``ref``, the read-back ``now`` and
      the journal; errors become ``{"ok": false, "error", "code"}``. Text
      stays the default.
    """
    if zone not in (READ, REVERSIBLE, DESTRUCTIVE):
        raise ValueError(f"unknown zone {zone!r}")

    def register(function: Callable) -> Callable:
        name = function.__name__
        writes = zone != READ
        signature = inspect.signature(function, eval_str=True)
        params = list(signature.parameters)

        @functools.wraps(function)
        def guarded(*args, **kwargs):
            as_json = False
            if writes:
                try:
                    as_json = to_bool(kwargs.pop("as_json", False), "as_json")
                except ValueError as problem:
                    return f"Error in {name} [bad_input]: {problem}"
            given = dict(zip(params, args), **kwargs)
            answer, steps, results, notices = _guarded(args, kwargs, given)
            if as_json:
                body = _as_json(answer, steps, results, _with_defaults(args, kwargs, given))
                if notices:
                    body["notice"] = " ".join(notices)
                return _json(body)
            note = ("\nNote: " + " ".join(notices)) if notices else ""
            if isinstance(answer, _Failure):
                return answer.text + note
            if isinstance(answer, (NotDone, ReadBack)):
                answer = str(answer)
            if steps:
                if isinstance(answer, dict) and "journal" not in answer:
                    answer["journal"] = steps
                elif isinstance(answer, str) and not answer.startswith("Error"):
                    answer += "\nJournal: " + "; ".join(
                        f"#{step['n']} {step['text']}" for step in steps[:8])
                    if len(steps) > 8:
                        answer += f"; ... {len(steps) - 8} more"
            if isinstance(answer, dict) and notices:
                answer["notice"] = " ".join(notices)
            if isinstance(answer, list) and notices:
                answer = {"items": answer, "notice": " ".join(notices)}
            if isinstance(answer, (dict, list)):
                return _json(answer)
            return answer + note if isinstance(answer, str) else answer

        def _guarded(args, kwargs, given):
            harmless = unless is not None and unless(given)
            if not harmless and _ZONE_ORDER.index(zone) > _ZONE_ORDER.index(max_zone()):
                message = (f"{name} is a {zone} tool and this server is limited to "
                           f"'{max_zone()}' (ABLETON_MCP_MAX_ZONE). Ask the user before going on.")
                return (_Failure("zone_not_allowed",
                                 f"Not executed [zone_not_allowed]: {message}", message),
                        [], [], [])
            confirmed = False
            if zone == DESTRUCTIVE and not harmless:
                try:
                    confirmed = to_bool(given.get("confirm", False), "confirm")
                except ValueError:
                    confirmed = False
                if not confirmed:
                    message = (f"{name} is destructive ({summary}). Ask the user; if they "
                               "agree, call it again with confirm=true.")
                    return (_Failure("needs_confirmation",
                                     f"Not executed [needs_confirmation]: {message}", message),
                            [], [], [])
            live.confirmed, live.journal, live.results, live.notices = confirmed, [], [], []
            try:
                answer = _run(args, kwargs)
                steps, results = list(live.journal), list(live.results)
                notices = list(dict.fromkeys(live.notices))  # each text once
            finally:
                live.confirmed, live.journal, live.results, live.notices = False, None, None, None
            return answer, steps, results, notices

        def _with_defaults(args, kwargs, given):
            try:
                bound = signature.bind_partial(*args, **kwargs)
            except TypeError:
                return given
            bound.apply_defaults()
            return dict(bound.arguments)

        def _as_json(answer, steps, results, given) -> dict:
            journal = [{"n": step.get("n"), "text": step.get("text")} for step in steps]
            if isinstance(answer, _Failure):
                body = {"ok": False, "error": answer.message, "code": answer.code}
                body.update(write_target(name, given, results))
                # journal and notice have fields of their own (link.py lifts them out)
                details = {key: value for key, value in (answer.details or {}).items()
                           if key not in ("journal", "notice")}
                if details:
                    body["details"] = details
                if journal:  # steps made before the failure, for undo_ai_change
                    body["journal"] = journal
                return body
            if isinstance(answer, NotDone):
                body = {"ok": False, "error": str(answer), "code": answer.code}
                body.update(write_target(name, given, results))
                if journal:
                    body["journal"] = journal
                return body
            body = {"ok": True, "tool": name}
            body.update(write_target(name, given, results))
            if isinstance(answer, (dict, list)):
                body["now"] = _without_journal(answer)
            elif isinstance(answer, ReadBack):
                body["message"], body["now"] = str(answer), answer.now
            else:
                body["message"] = answer
                if len(results) == 1:
                    body["now"] = _without_journal(results[0])
                elif results:  # one entry per write command, in order
                    body["now"] = [_without_journal(result) for result in results]
            body["journal"] = journal
            return body

        def _run(args, kwargs):
            try:
                return function(*args, **kwargs)
            except LiveError as problem:
                extra = ""
                shown = {key: value for key, value in (problem.details or {}).items()
                         if key != "notice"}          # the notice comes as "Note:" below
                if shown:
                    extra = " | " + json.dumps(shown, ensure_ascii=False, default=str)
                return _Failure(problem.code, f"Error in {name} [{problem.code}]: {problem}{extra}",
                                str(problem), problem.details)
            except (ValueError, TypeError, KeyError) as problem:
                return _Failure("bad_input", f"Error in {name} [bad_input]: {problem}",
                                str(problem))
            except Exception as problem:  # last line of defence, with traceback in the log
                log.exception("tool %s failed", name)
                text = f"{type(problem).__name__}: {problem}"
                return _Failure("internal", f"Error in {name} [internal]: {text}", text)

        if writes:
            if "as_json" in signature.parameters:
                raise ValueError(f"{name}: write tools get as_json from @tool")
            # FastMCP builds the tool schema from this signature
            guarded.__signature__ = signature.replace(parameters=[
                *signature.parameters.values(),
                inspect.Parameter("as_json", inspect.Parameter.KEYWORD_ONLY,
                                  default=False, annotation=BoolLike)])
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
