"""Commands about the bridge itself: version, register listing, hot reload."""

import sys
import time

from .. import journal, reloader, settings
from ..errors import BAD_PARAMS, DISABLED, CommandError
from ..liveaccess import peek
from ..registry import DESTRUCTIVE, READ, REVERSIBLE, Bool, Int, Text, command


def _live_version(live):
    app = live.app
    parts = [peek(app, name, lambda: None)() for name in
             ("get_major_version", "get_minor_version", "get_bugfix_version")]
    return ".".join(str(p) for p in parts if p is not None) or None


@command("get_version", zone=READ,
         summary="Bridge version, source fingerprint and load state (health check)",
         aliases=("ping",))
def get_version(live):
    hub = live.hub
    on_disk = reloader.fingerprint()
    core_now = reloader.fingerprint(only_core=True)["hash"]
    listener = peek(live.surface, "listener")
    return {
        "bridge_version": settings.BRIDGE_VERSION,
        "command_count": len(hub.registry),
        "file_hash": on_disk["hash"],
        "mtime": on_disk["newest_mtime"],
        "source_files": on_disk["files"],
        "script_dir": reloader.package_dir(),
        "loaded_at": int(hub.loaded.loaded_at),
        "reload_count": hub.reload_count,
        "core_changed_since_start": core_now != hub.state.get("core_hash_at_start",
                                                               hub.loaded.core_hash),
        "uptime_s": int(time.time() - hub.started_at),
        "requests_served": hub.served,
        "requests_failed": hub.failed,
        "clients": listener.client_count() if listener is not None else None,
        "eval_enabled": settings.eval_allowed(),
        "live_version": _live_version(live),
        "python": "%d.%d.%d" % sys.version_info[:3],
    }


@command("list_commands", zone=READ,
         summary="The command register: names, zones, parameters",
         params=[Text("zone", None)])
def list_commands(live, zone):
    entries = live.hub.registry.describe()
    if zone:
        entries = [e for e in entries if e["zone"] == zone.strip().lower()]
    return {"count": len(entries), "commands": entries}


@command("hot_reload", zone=READ, timeout=20.0,
         summary="Reload handlers and support modules from disk without restarting Live")
def hot_reload(live):
    hub = live.hub
    hub.state.setdefault("core_hash_at_start", hub.loaded.core_hash)
    before = set(hub.registry.names())
    try:
        fresh = hub.reload()
    except SyntaxError as problem:
        return {"hot_reload": "error", "kept_previous": True,
                "reason": "syntax error in %s line %s: %s"
                          % (problem.filename, problem.lineno, problem.msg)}
    except Exception as problem:
        return {"hot_reload": "error", "kept_previous": True,
                "reason": "%s: %s" % (type(problem).__name__, problem)}
    after = set(fresh.registry.names())
    core_changed = fresh.core_hash != hub.state["core_hash_at_start"]
    return {
        "hot_reload": "ok",
        "commands": len(after),
        "added": sorted(after - before),
        "removed": sorted(before - after),
        "modules_reloaded": len(fresh.modules),
        "reload_count": hub.reload_count,
        "file_hash": reloader.fingerprint()["hash"],
        "core_changed": core_changed,
        "note": "Core modules changed on disk; restart Live to load them."
                if core_changed else "",
    }


@command("eval_code", zone=DESTRUCTIVE,
         summary="Evaluate a Python expression inside Live (off unless enabled, see settings)",
         params=[Text("code")])
def eval_code(live, code):
    if not settings.eval_allowed():
        raise CommandError(
            DISABLED,
            "eval_code is switched off. To enable it, create the file '%s' in %s "
            "or start Live with %s=1." % (settings.EVAL_FLAG_FILE, reloader.package_dir(),
                                         settings.EVAL_ENV_SWITCH),
        )
    if not code.strip():
        raise CommandError(BAD_PARAMS, "code is empty")
    live.record("Evaluated Python inside Live: %s" % code[:120], kind="none")
    scope = {"live": live, "song": live.song, "app": live.app, "Live": live.live_module()}
    return {"value": repr(eval(code, scope))}


@command("list_changes", zone=READ,
         summary="The change journal: numbered steps made through the bridge",
         params=[Int("limit", 30), Bool("only_active", False)])
def list_changes(live, limit, only_active):
    return journal.listing(live.hub, limit, only_active)


@command("undo_change", zone=REVERSIBLE, journal=False, timeout=180.0,
         summary="Take back exactly one journal step by its number",
         params=[Int("n")])
def undo_change(live, n):
    return journal.undo(live.hub, n)


@command("note_change", zone=REVERSIBLE,
         summary="Add a journal entry for a change made outside the bridge (keys, files)",
         params=[Text("text"), Text("undo", "none")])
def note_change(live, text, undo):
    if undo not in (journal.LIVE_UNDO, journal.NONE):
        raise CommandError(BAD_PARAMS, "undo must be 'live_undo' or 'none'")
    live.record(text.strip()[:300], kind=undo)
    return {"noted": True}


@command("get_safety_status", zone=READ,
         summary="Safety settings of the bridge and the state of the change journal")
def get_safety_status(live):
    by_zone = {}
    for entry in live.hub.registry.describe():
        by_zone[entry["zone"]] = by_zone.get(entry["zone"], 0) + 1
    return {
        "confirm_required_for_destructive": settings.confirm_required(),
        "eval_enabled": settings.eval_allowed(),
        "commands_by_zone": by_zone,
        "destructive_commands": sorted(e["name"] for e in live.hub.registry.describe()
                                       if e["zone"] == DESTRUCTIVE),
        "journal": journal.status(live.hub),
    }
