"""Safety tools: what the assistant may do, and the journal of what it did."""

from __future__ import annotations

from ..coerce import BoolLike, IntLike, to_bool, to_int
from ..core import DESTRUCTIVE, READ, REVERSIBLE, TOOLS, live, max_zone, tool
from ..link import LiveError


@tool(READ)
def get_safety_status() -> str:
    """Show the safety rules in force and the state of the change journal.

    Lists which tools are destructive (they need confirm=true), the highest
    zone this server is allowed to use, whether the bridge insists on
    confirmation, and how many journal steps exist and can be taken back.
    """
    zones = {READ: [], REVERSIBLE: [], DESTRUCTIVE: []}
    for name, entry in sorted(TOOLS.items()):
        zones[entry["zone"]].append(name)
    answer = {
        "max_zone_allowed": max_zone(),
        "tools_by_zone": {zone: len(names) for zone, names in zones.items()},
        "destructive_tools_need_confirm": zones[DESTRUCTIVE],
    }
    try:
        answer["bridge"] = live.call("get_safety_status")
    except LiveError as problem:
        answer["bridge"] = f"not reachable: {problem}"
    return answer


@tool(READ)
def list_ai_changes(limit: IntLike = 30, only_active: BoolLike = False) -> str:
    """List the numbered journal of changes made through this bridge.

    Each line: number, time, what changed, and how it can be taken back:
    'exact' (undo_ai_change restores the previous state), 'live_undo' (only
    Live's own undo, while it is the latest step) or 'none'. Steps already
    taken back are marked.

    - limit: show the most recent N steps (0 = all)
    - only_active: leave out steps that were taken back
    """
    result = live.call("list_changes", limit=to_int(limit, "limit"),
                       only_active=to_bool(only_active, "only_active"))
    if not result["count"]:
        return "The journal is empty: nothing was changed through the bridge in this session."
    rows = [f"{result['shown']} of {result['count']} journal steps"
            + (f" (file: {result['journal_file']})" if result.get("journal_file") else "")]
    for entry in result["entries"]:
        mark = " [taken back]" if entry["state"] == "undone" else ""
        rows.append(f"#{entry['n']} {entry['time']} {entry['text']}  (undo: {entry['undo']}){mark}")
    return "\n".join(rows)


@tool(REVERSIBLE)
def undo_ai_change(number: IntLike) -> str:
    """Take back exactly one journal step, leaving all other steps as they are.

    Works for steps marked 'exact' in list_ai_changes. If the user (or a
    later step) changed the same thing since, nothing is touched and the
    answer says so. Steps marked 'live_undo' can only be taken back with
    the undo tool while they are the most recent change in Live.

    - number: the step number from list_ai_changes (the #n shown after a change)
    """
    wanted = to_int(number, "number")
    result = live.call("undo_change", n=wanted)
    return f"Took back #{result['undone']}: {result['text']}"
