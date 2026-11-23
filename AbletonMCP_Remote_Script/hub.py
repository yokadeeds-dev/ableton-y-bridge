"""Dispatcher between the wire and the command register."""

import sys
import threading
import time
import traceback

from . import reloader
from .errors import BAD_PARAMS, INTERNAL, CommandError
from .registry import Later


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
        return fresh

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

            result = self.gate.call(work, spec.timeout)
            hops = 0
            while isinstance(result, Later):
                hops += 1
                if hops > 5000:
                    raise CommandError(INTERNAL, "command did not come to an end")
                result = self.gate.call(result.finish, spec.timeout,
                                        wait_ticks=result.ticks)
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
