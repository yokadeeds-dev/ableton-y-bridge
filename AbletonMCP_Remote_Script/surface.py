# Copyright (C) 2026 Yoka
# SPDX-License-Identifier: AGPL-3.0-only
"""The control surface object Live talks to.

It does three things: start the TCP listener, give socket threads a way into
Live's main thread, and shut both down again when Live removes the script.
"""

from _Framework.ControlSurface import ControlSurface

from . import settings
from .gate import MainThreadGate
from .hub import Hub
from .wire import Listener


class BridgeSurface(ControlSurface):
    def __init__(self, c_instance):
        ControlSurface.__init__(self, c_instance)
        self._gate = MainThreadGate()
        self._gate.adopt_current_thread()
        self._listener = None
        self._hub = None
        try:
            self._hub = Hub(self, self._gate)
        except Exception as problem:
            # Without handlers there is nothing to serve; say so in Live.
            self.log_message("[bridge] handlers failed to load: %r" % (problem,))
            self.show_message("Ableton Y Bridge: load error, see Log.txt")
            return
        self._listener = Listener(
            settings.HOST,
            settings.PORT,
            self._hub.handle,
            self._log,
            settings.MAX_REQUEST_BYTES,
        )
        self._listener.start()
        self._log("bridge %s up, %d commands" % (settings.BRIDGE_VERSION, len(self._hub.registry)))
        self.show_message(
            "Ableton Y Bridge %s on port %d" % (settings.BRIDGE_VERSION, settings.PORT)
        )

    @property
    def listener(self):
        return self._listener

    def update_display(self):
        # Live calls this on its main thread roughly every 100 ms.
        ControlSurface.update_display(self)
        self._gate.drain()
        if self._hub is not None:
            self._hub.tick()

    def disconnect(self):
        self._log("bridge going down")
        if self._listener is not None:
            self._listener.stop()
        self._gate.close()
        ControlSurface.disconnect(self)

    def _log(self, text):
        self.log_message("[bridge] " + text)
