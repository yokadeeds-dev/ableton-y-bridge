# Copyright (C) 2026 Yoka
# SPDX-License-Identifier: AGPL-3.0-only
"""Receives level and spectrum frames from an external analyzer over UDP.

The analyzer (``analyzer/audio_analyzer.py`` or the Max for Live device in
``m4l/``) sends one JSON datagram per measurement to this port. The feed
keeps only the latest frame; tools ask for it together with its age.
"""

from __future__ import annotations

import json
import logging
import os
import socket
import threading
import time
from typing import Optional, Tuple

log = logging.getLogger("ableton_mcp.analyzer")

DEFAULT_PORT = 7878
FRESH_SECONDS = 5.0
BAND_ORDER = ("sub", "low", "mid", "high", "air")
BAND_RANGES = {
    "sub": "20-60 Hz",
    "low": "60-250 Hz",
    "mid": "250 Hz-2 kHz",
    "high": "2-8 kHz",
    "air": "8-20 kHz",
}
SILENT = -990.0  # analyzers send -999 for "no signal"


class AnalyzerFeed:
    def __init__(self, port: Optional[int] = None):
        self.port = int(port or os.environ.get("ABLETON_MCP_ANALYZER_PORT", DEFAULT_PORT))
        self._frame: dict = {}
        self._stamp = 0.0
        self._lock = threading.Lock()
        self._running = False
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._listen, name="analyzer-feed", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._running = False

    def latest(self) -> Tuple[dict, float]:
        """(frame, age in seconds). An empty frame means nothing was received."""
        with self._lock:
            if not self._frame:
                return {}, float("inf")
            return dict(self._frame), time.time() - self._stamp

    def fresh(self) -> Optional[dict]:
        """The latest frame if it is recent enough to describe what plays now."""
        frame, age = self.latest()
        return frame if frame and age <= FRESH_SECONDS else None

    def _listen(self) -> None:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.settimeout(1.0)
        try:
            sock.bind(("", self.port))
        except OSError as problem:
            log.warning("analyzer feed: cannot listen on UDP %d (%s)", self.port, problem)
            self._running = False
            return
        log.info("analyzer feed listening on UDP %d", self.port)
        try:
            while self._running:
                try:
                    datagram, _sender = sock.recvfrom(8192)
                except socket.timeout:
                    continue
                except OSError:
                    break
                try:
                    frame = json.loads(datagram.decode("utf-8"))
                except (UnicodeDecodeError, ValueError):
                    continue
                if isinstance(frame, dict):
                    with self._lock:
                        self._frame = frame
                        self._stamp = time.time()
        finally:
            sock.close()


def audible_bands(frame: dict) -> dict:
    """Band levels of a frame without the 'no signal' placeholders."""
    bands = frame.get("bands") or {}
    return {name: float(level) for name, level in bands.items()
            if isinstance(level, (int, float)) and level > SILENT}
