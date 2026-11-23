# Copyright (C) 2026 Yoka
# SPDX-License-Identifier: AGPL-3.0-only
"""Numbered journal of the changes made through the bridge, with single-step undo.

Every command that changes the Live Set gets an entry with a running number,
for example ``#12 Track 'Bass' fader: -10.0 dB -> 0.0 dB``. `undo` takes back
exactly that one step and leaves all other steps alone, which Live's own
linear undo history cannot do.

How an entry can be taken back is its *kind*:

* ``exact``     - the handler stored how to restore the previous state; it is
                  restored only if the Set still looks the way the command
                  left it (if the user changed the value since, it stays)
* ``live_undo`` - recorded only; Live's own undo can take it back as long as
                  it is the most recent step
* ``none``      - recorded only (transport-like actions, file operations)

The journal lives in ``hub.state`` and so survives hot reloads. The restore
functions hold on to Live objects (tracks, clips, parameters), not indices,
so they stay correct when tracks are inserted or moved. They end with the
Live session; the text of the journal is also appended to a file per session.
"""

import json
import os
import threading
import time

from . import settings
from .errors import BUSY, NOT_FOUND, UNSUPPORTED, CommandError
from .registry import Later

EXACT, LIVE_UNDO, NONE = "exact", "live_undo", "none"
ACTIVE, UNDONE = "active", "undone"
CHANGED_SINCE = "changed_since"
KEEP_RESTORABLE = 400  # older entries keep their text but lose the restore function

_lock = threading.Lock()


def _book(hub):
    book = hub.state.get("journal")
    if book is None:
        book = hub.state["journal"] = {
            "next": 1,
            "entries": {},
            "order": [],
            "file": None,
            "file_failed": False,
            "started": time.time(),
        }
    return book


def _safe_name(text):
    kept = "".join(ch if ch.isalnum() or ch in " -_." else "_" for ch in str(text)).strip(" .")
    return kept or "_untitled"


def prepare(hub, song):
    """Decide where this session's journal file goes. Main thread only."""
    book = _book(hub)
    if book["file"] is not None or book["file_failed"]:
        return
    root = settings.journal_dir()
    if not root:
        book["file_failed"] = True
        return
    try:
        set_name = getattr(song, "name", "") or ""
    except Exception:
        set_name = ""
    folder = os.path.join(root, _safe_name(set_name))
    stamp = time.strftime("%Y-%m-%d_%H%M%S", time.localtime(book["started"]))
    book["file"] = os.path.join(folder, stamp + ".jsonl")


def _append_to_file(book, record):
    path = book.get("file")
    if not path or book.get("file_failed"):
        return
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
    except OSError:
        book["file_failed"] = True  # journalling to disk must never break a command


def compact(params, limit=160):
    """Short text form of a params dict for the journal."""
    shown = {}
    for key, value in (params or {}).items():
        if isinstance(value, (list, tuple)):
            shown[key] = "<%d items>" % len(value)
        elif isinstance(value, dict):
            shown[key] = "<object>"
        else:
            shown[key] = value
    text = json.dumps(shown, ensure_ascii=False, default=str)
    return text if len(text) <= limit else text[:limit - 3] + "..."


def public(entry):
    return {
        "n": entry["n"],
        "time": time.strftime("%H:%M:%S", time.localtime(entry["at"])),
        "command": entry["command"],
        "text": entry["text"],
        "undo": entry["kind"],
        "state": entry["state"],
    }


def add(hub, command, params, text, undo=None, valid=None, kind=None):
    """Append an entry and return its public form."""
    if kind is None:
        kind = EXACT if undo is not None else LIVE_UNDO
    with _lock:
        book = _book(hub)
        number = book["next"]
        book["next"] = number + 1
        entry = {
            "n": number,
            "at": time.time(),
            "command": command,
            "params": compact(params),
            "text": text,
            "kind": kind,
            "state": ACTIVE,
            "undo": undo,
            "valid": valid,
        }
        book["entries"][number] = entry
        book["order"].append(number)
        for old in book["order"][:-KEEP_RESTORABLE]:
            stale = book["entries"].get(old)
            if stale is not None and stale["undo"] is not None:
                stale["undo"] = stale["valid"] = None
                if stale["kind"] == EXACT and stale["state"] == ACTIVE:
                    stale["kind"] = LIVE_UNDO
        _append_to_file(book, {"n": number, "at": entry["at"], "command": command,
                               "params": entry["params"], "text": text, "undo": kind})
    return public(entry)


def listing(hub, limit=30, only_active=False):
    with _lock:
        book = _book(hub)
        numbers = list(book["order"])
        entries = [public(book["entries"][n]) for n in numbers]
        path, total = book.get("file"), len(numbers)
    if only_active:
        entries = [e for e in entries if e["state"] == ACTIVE]
    if limit and limit > 0:
        entries = entries[-limit:]
    return {"count": total, "shown": len(entries), "entries": entries,
            "journal_file": None if not path else path}


def status(hub):
    with _lock:
        book = _book(hub)
        entries = list(book["entries"].values())
        return {
            "entries": len(entries),
            "undoable": sum(1 for e in entries if e["kind"] == EXACT and e["state"] == ACTIVE),
            "undone": sum(1 for e in entries if e["state"] == UNDONE),
            "journal_file": book.get("file"),
            "session_started": time.strftime("%Y-%m-%d %H:%M:%S",
                                             time.localtime(book["started"])),
        }


def _after(outcome, then):
    """Call ``then(value)`` once ``outcome`` (possibly a Later chain) is final."""
    if isinstance(outcome, Later):
        return Later(lambda: _after(outcome.finish(), then), outcome.ticks)
    return then(outcome)


def undo(hub, number):
    """Take back entry ``number``. Main thread only; may span several ticks."""
    with _lock:
        entry = _book(hub)["entries"].get(number)
    if entry is None:
        raise CommandError(NOT_FOUND, "there is no journal entry #%s" % number)
    if entry["state"] == UNDONE:
        raise CommandError(BUSY, "#%d was already taken back" % number)
    if entry["kind"] != EXACT or entry["undo"] is None:
        advice = ("Live's own undo can take it back while it is the most recent step"
                  if entry["kind"] == LIVE_UNDO else "it cannot be taken back from here")
        raise CommandError(UNSUPPORTED, "#%d (%s) was only recorded; %s"
                           % (number, entry["text"], advice))
    if entry["valid"] is not None:
        objection = entry["valid"]()
        if objection:
            raise CommandError(
                CHANGED_SINCE,
                "#%d not taken back: %s. The current state was left as it is."
                % (number, objection),
            )

    def done(detail):
        with _lock:
            entry["state"] = UNDONE
            _append_to_file(_book(hub), {"undone": number, "at": time.time()})
        answer = {"undone": number, "text": entry["text"]}
        if isinstance(detail, dict):
            answer.update(detail)
        return answer

    return _after(entry["undo"](), done)
