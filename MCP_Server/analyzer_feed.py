# Copyright (C) 2026 Yoka
# SPDX-License-Identifier: AGPL-3.0-only
"""Receives level and spectrum frames from external analyzers over UDP.

Two senders share the port:

* ``analyzer/audio_analyzer.py`` measures what Windows plays (the master) and
  sends one JSON datagram per measurement.
* The Max for Live device "Y Meter" (``m4l/``) sits on any track and sends an
  OSC message ``/ytrack <track name> rms peak sub low mid high air`` (linear
  amplitudes) about five times a second.

The feed keeps the latest master frame and the latest frame per track name;
tools ask for them together with their age. When several MCP servers run at
the same time, one of them owns the port and relays every frame to the
others (see ``AnalyzerFeed``).
"""

from __future__ import annotations

import json
import logging
import math
import os
import socket
import struct
import threading
import time
from typing import Dict, List, Optional, Tuple

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
TRACK_ADDRESS = "/ytrack"
TRACK_FIELDS = ("rms", "peak") + BAND_ORDER


def _osc_string(data: bytes, at: int) -> Tuple[str, int]:
    end = data.index(b"\0", at)
    text = data[at:end].decode("utf-8", "replace")
    return text, (end + 4) & ~3


def parse_osc(data: bytes) -> Tuple[str, List[object]]:
    """Address and arguments of one OSC message (types s, i, f, d, h)."""
    address, at = _osc_string(data, 0)
    if at >= len(data) or data[at:at + 1] != b",":
        return address, []
    tags, at = _osc_string(data, at)
    values: List[object] = []
    for tag in tags[1:]:
        if tag == "s":
            text, at = _osc_string(data, at)
            values.append(text)
        elif tag == "i":
            values.append(struct.unpack(">i", data[at:at + 4])[0]); at += 4
        elif tag == "f":
            values.append(struct.unpack(">f", data[at:at + 4])[0]); at += 4
        elif tag == "d":
            values.append(struct.unpack(">d", data[at:at + 8])[0]); at += 8
        elif tag == "h":
            values.append(struct.unpack(">q", data[at:at + 8])[0]); at += 8
        else:
            raise ValueError("unsupported OSC type %r" % tag)
    return address, values


def amp_db(value: float) -> float:
    return round(20.0 * math.log10(value), 1) if value > 1e-9 else -999.0


def track_frame(values: List[object]) -> Optional[Tuple[str, dict]]:
    """(track name, frame in dB) from the arguments of a /ytrack message."""
    if len(values) < 1 + len(TRACK_FIELDS):
        return None
    name = str(values[0]).strip()
    if len(name) >= 2 and name[0] == name[-1] == '"':  # Max quotes names with spaces
        name = name[1:-1]
    numbers = values[1:1 + len(TRACK_FIELDS)]
    if not all(isinstance(v, (int, float)) for v in numbers):
        return None
    levels = dict(zip(TRACK_FIELDS, (float(v) for v in numbers)))
    frame = {
        "rms_db": amp_db(levels["rms"]),
        "peak_db": amp_db(levels["peak"]),
        "bands": {band: amp_db(levels[band]) for band in BAND_ORDER},
    }
    return name, frame


def decode_datagram(datagram: bytes) -> Tuple[Optional[dict], Optional[Tuple[str, dict]]]:
    """(master frame, track frame); at most one of them is set."""
    if datagram[:1] == b"/":
        address, values = parse_osc(datagram)
        if address == TRACK_ADDRESS:
            return None, track_frame(values)
        if address.startswith("{"):  # JSON sent as an OSC address by an older device
            datagram = address.encode("utf-8")
        else:
            return None, None
    elif datagram[:1] == b"{" and b"\0" in datagram:
        datagram = datagram.split(b"\0", 1)[0]
    frame = json.loads(datagram.decode("utf-8"))
    return (frame if isinstance(frame, dict) else None), None


SUBSCRIBE = b"YSUB"  # "send me a copy of every frame"
LOOPBACK = "127.0.0.1"


def _quiet_udp(sock: socket.socket) -> None:
    """Windows reports an ICMP 'port unreachable' from an earlier sendto as an
    error on the next recvfrom; switch that off where possible."""
    if hasattr(socket, "SIO_UDP_CONNRESET"):
        try:
            sock.ioctl(socket.SIO_UDP_CONNRESET, False)
        except (OSError, ValueError):
            pass


class AnalyzerFeed:
    """Listens for analyzer frames; several MCP servers can run at once.

    Only one socket can own the UDP port. The server that gets it (the hub)
    receives the frames and passes a copy of each to every other server that
    asked for it: those bind a private loopback port and send ``YSUB`` to the
    hub every ``renew_s`` seconds. They also try to take the port over at the
    same pace, so when the hub ends another server becomes the hub. Senders
    (the analyzer, Y Meter) need not know about any of this.
    """

    renew_s = 2.0
    subscriber_ttl_s = 6.0
    poll_s = 0.25

    def __init__(self, port: Optional[int] = None):
        self.port = int(port or os.environ.get("ABLETON_MCP_ANALYZER_PORT", DEFAULT_PORT))
        self._frame: dict = {}
        self._stamp = 0.0
        self._tracks: Dict[str, Tuple[dict, float]] = {}
        self._lock = threading.Lock()
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self.role = "stopped"  # "hub", "relayed" or "stopped"
        self.subscribers = 0

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._listen, name="analyzer-feed", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._running = False
        thread = self._thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=2.0)

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

    def tracks(self, max_age: float = FRESH_SECONDS) -> Dict[str, dict]:
        """Latest frame per track name, only those younger than ``max_age``."""
        now = time.time()
        with self._lock:
            return {name: dict(frame, age_s=round(now - stamp, 2))
                    for name, (frame, stamp) in self._tracks.items()
                    if now - stamp <= max_age}

    def accept(self, datagram: bytes) -> None:
        """Store one received datagram (also used by the tests)."""
        try:
            master, track = decode_datagram(datagram)
        except (UnicodeDecodeError, ValueError, struct.error, IndexError):
            return
        now = time.time()
        with self._lock:
            if master is not None:
                self._frame = master
                self._stamp = now
            if track is not None:
                self._tracks[track[0]] = (track[1], now)

    def _bind_hub(self) -> Optional[socket.socket]:
        """The shared port, exclusively, or None if another socket holds it."""
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):  # Windows: nobody may take it over
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        try:
            sock.bind((LOOPBACK, self.port))
        except OSError:
            sock.close()
            return None
        _quiet_udp(sock)
        sock.settimeout(self.poll_s)
        return sock

    def _bind_private(self) -> socket.socket:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.bind((LOOPBACK, 0))
        _quiet_udp(sock)
        sock.settimeout(self.poll_s)
        return sock

    def _listen(self) -> None:
        hub: Optional[socket.socket] = None
        private: Optional[socket.socket] = None
        subscribers: Dict[Tuple[str, int], float] = {}
        last_try = 0.0
        try:
            while self._running:
                now = time.time()
                if hub is None and now - last_try >= self.renew_s:
                    last_try = now
                    hub = self._bind_hub()
                    if hub is not None:
                        if private is not None:
                            private.close()
                            private = None
                        self.role = "hub"
                        log.info("analyzer feed: receiving on UDP %d", self.port)
                    else:
                        if private is None:
                            private = self._bind_private()
                            log.info("analyzer feed: UDP %d is taken, asking its owner "
                                     "for copies", self.port)
                        self.role = "relayed"
                        try:
                            private.sendto(SUBSCRIBE, (LOOPBACK, self.port))
                        except OSError:
                            pass
                sock = hub if hub is not None else private
                if sock is None:
                    time.sleep(self.poll_s)
                    continue
                try:
                    datagram, sender = sock.recvfrom(65535)
                except socket.timeout:
                    continue
                except OSError:
                    continue  # e.g. a reset reported for an earlier send
                if hub is not None:
                    if datagram == SUBSCRIBE:
                        subscribers[sender] = now
                        self.subscribers = len(subscribers)
                        continue
                    for address, seen in list(subscribers.items()):
                        if now - seen > self.subscriber_ttl_s:
                            del subscribers[address]
                            continue
                        try:
                            hub.sendto(datagram, address)
                        except OSError:
                            pass
                    self.subscribers = len(subscribers)
                elif datagram == SUBSCRIBE:
                    continue
                self.accept(datagram)
        finally:
            for sock in (hub, private):
                if sock is not None:
                    sock.close()
            self.role = "stopped"
            self.subscribers = 0


def audible_bands(frame: dict) -> dict:
    """Band levels of a frame without the 'no signal' placeholders."""
    bands = frame.get("bands") or {}
    return {name: float(level) for name, level in bands.items()
            if isinstance(level, (int, float)) and level > SILENT}
