# Copyright (C) 2026 Yoka
# SPDX-License-Identifier: AGPL-3.0-only
"""Dispatcher between the wire and the command register."""

import sys
import threading
import time
import traceback

from . import reloader
from .errors import BAD_PARAMS, INTERNAL, TIMEOUT, CommandError
from .registry import READ, Later


class Hub(object):
    """Owns the register and runs one request at a time through the gate.

    ``state`` is a plain dict that survives hot reloads; handlers keep
    long-lived data there (for example the tempo map of the tempo follower).
    """

    def __init__(self, surface, gate):
        self.surface = surface
        self.gate = gate
        self.state = {}
        self.started_at = time.time()
        self.reload_count = 0
        self.served = 0
        self.failed = 0
        self._swap_lock = threading.Lock()
        self._loaded = reloader.load()
        self.state["core_hash_at_start"] = self._loaded.core_hash
        self._start_tickers()

    # -- register access ---------------------------------------------------

    @property
    def registry(self):
        return self._loaded.registry

    @property
    def loaded(self):
        return self._loaded

    def reload(self):
        """Replace handlers and support modules by what is on disk now."""
        fresh = reloader.load()
        with self._swap_lock:
            self._loaded = fresh
            self.reload_count += 1
        self._start_tickers()
        return fresh

    def _start_tickers(self):
        """Enter the tickers the handlers declared with ``registry.ticker``."""
        declared = getattr(self._loaded.registry, "tickers", {})
        if declared:
            self.state.setdefault("tickers", {}).update(declared)

    def context(self):
        return self._loaded.context_class(self.surface, self)

    # -- request handling (socket threads) ---------------------------------

    def handle(self, message):
        """Answer one decoded request. Never raises."""
        name = None
        try:
            if not isinstance(message, dict):
                raise CommandError(BAD_PARAMS, "a request must be a JSON object")
            name = message.get("type")
            if not isinstance(name, str) or not name:
                raise CommandError(BAD_PARAMS, "request has no 'type'")
            loaded = self._loaded
            spec = loaded.registry.get(name)
            arguments = spec.bind(message.get("params"))
            # Policy (confirmation of destructive commands) and the change
            # journal live in the reloadable context class.
            admit = getattr(loaded.context_class, "admit", None)
            if admit is not None:
                admit(spec, message)
            used = []

            def work():
                context = loaded.context_class(self.surface, self, message)
                used.append(context)
                return spec.handler(context, **arguments)

            def late(job):
                # The client got a timeout, but Live ran the step to its end:
                # journal what it did (main thread, after the step). A step that
                # failed is not journaled, as on the path without a timeout.
                # Nobody waits for a reply any more: the untitled-Set notice is
                # kept for the next change, and trouble goes to the gate, which
                # counts it (bridge_status: late_failures).
                try:
                    if isinstance(job.value, Later):
                        self._log("%s timed out; its later steps are dropped" % spec.name)
                    if job.failure is None:
                        self._journal_anyway(used, spec, arguments, notify=False, strict=True)
                except Exception:
                    self._log("late journal for %s failed:\n%s"
                              % (spec.name, traceback.format_exc()))
                    raise

            try:
                result = self.gate.call(work, spec.timeout, late=late)
                hops = 0
                while isinstance(result, Later):
                    hops += 1
                    if hops > 5000:
                        raise CommandError(INTERNAL, "command did not come to an end")
                    result = self.gate.call(result.finish, spec.timeout,
                                            wait_ticks=result.ticks, late=late)
            except CommandError as problem:
                if problem.code == TIMEOUT:
                    self._after_timeout(problem, used, spec, arguments, loaded.context_class)
                raise
            if used and hasattr(used[0], "finish"):
                result = used[0].finish(spec, arguments, result)
            self.served += 1
            return {"status": "success", "result": {} if result is None else result}
        except CommandError as problem:
            self.failed += 1
            self._log("%s refused: %s" % (name, problem.message))
            return problem.as_reply()
        except Exception as problem:
            self.failed += 1
            self._log("%s crashed:\n%s" % (name, traceback.format_exc()))
            return {
                "status": "error",
                "code": INTERNAL,
                "message": "%s: %s" % (type(problem).__name__, problem),
            }

    def _journal_anyway(self, used, spec, arguments, notify=True, strict=False):
        """Journal the steps a command made although its reply was a timeout.

        Returns the entries and the untitled-Set notice (or None). With
        ``notify`` False the notice is not used up; with ``strict`` a failure
        is raised instead of logged.
        """
        if not used or not hasattr(used[0], "finish"):
            return [], None
        context = used[0]
        try:
            finish_late = getattr(context, "finish_late", None)  # an older context has none
            if finish_late is not None:
                done = finish_late(spec, arguments, notify)
            else:
                done = context.finish(spec, arguments, {})
        except Exception:
            if strict:
                raise
            self._log("journal after timeout failed:\n%s" % traceback.format_exc())
            return [], None
        done = done if isinstance(done, dict) else {}
        entries = done.get("journal") or []
        if entries:
            self._log("%s timed out after it changed the Set; journaled as %s"
                      % (spec.name, ", ".join("#%d" % e["n"] for e in entries)))
        return entries, done.get("notice")

    @staticmethod
    def _journals(context_class, spec):
        """Whether a command of this kind gets a journal entry (the context
        class owns the rule; the fallback is the rule of older contexts)."""
        rule = getattr(context_class, "journals", None)
        if rule is not None:
            return rule(spec)
        return spec.zone != READ and getattr(spec, "journal", True)

    def _after_timeout(self, problem, used, spec, arguments, context_class=None):
        """A timeout after the command already changed something must not lose
        the journal entry (single-step undo depends on it)."""
        if problem.details.get("still_running"):
            # the gate calls late() once the step is over; it journals then
            problem.message += ". Later steps of the command, if any, are dropped."
            if self._journals(context_class, spec):
                problem.message += (" If the step succeeds and changes the Set, it is "
                                     "journaled then: list_ai_changes shows it.")
        elif used:
            # an earlier step of the command ran, a later one was dropped
            try:
                entries, notice = self._journal_anyway(used, spec, arguments, strict=True)
            except Exception:
                self._log("journal after timeout failed:\n%s" % traceback.format_exc())
                entries, notice = [], None
                problem.details["journal_failed"] = True
                problem.message += (". Earlier steps of it did run, but their journal entry "
                                    "failed (see Live's log)")
            if entries:
                problem.details["journal"] = entries
                problem.message += (". Earlier steps of it did run and are journaled: %s"
                                    % ", ".join("#%d" % e["n"] for e in entries))
            if notice:
                problem.details["notice"] = notice
        problem.args = (problem.message,)

    # -- periodic work (main thread) ---------------------------------------

    def tick(self):
        """Run periodic callbacks, about ten times a second.

        ``state["tickers"]`` maps a key to ``(module, function)`` names
        relative to the package. Names instead of function objects, so that
        a hot reload swaps the code of a running ticker as well.
        """
        tickers = self.state.get("tickers")
        if not tickers:
            return
        context = None
        for key, (module_name, function_name) in list(tickers.items()):
            module = sys.modules.get("%s.%s" % (reloader.PACKAGE, module_name))
            callback = getattr(module, function_name, None)
            if callback is None:
                tickers.pop(key, None)
                continue
            if context is None:
                context = self.context()
            try:
                callback(context)
            except Exception:
                self._log("ticker %s failed and was stopped:\n%s" % (key, traceback.format_exc()))
                tickers.pop(key, None)

    def _log(self, text):
        try:
            self.surface.log_message("[bridge] " + text)
        except Exception:
            pass
