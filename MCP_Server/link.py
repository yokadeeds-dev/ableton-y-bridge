"""Client side of the bridge: one TCP connection to the Remote Script in Live.

`LiveLink.call("set_tempo", tempo=120)` sends ``{"type", "params"}``, waits
for the reply object and returns its ``result``. An error reply becomes a
`LiveError`. The connection is opened on first use and reopened once if it
turns out to be dead.

After connecting, the link asks the bridge for its command register. From it
come the per-command timeouts and the knowledge which commands change the
Live Set (those are paced by a token bucket so that a burst of edits cannot
flood Live).
"""

from __future__ import annotations

import json
import logging
import os
import select
import socket
import threading
import time
from typing import Any, Dict, Optional

log = logging.getLogger("ableton_mcp.link")

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 9877
_GRACE = 5.0  # seconds added to the bridge's own timeout before the client gives up


class LiveError(Exception):
    """The bridge answered with an error, or could not be reached."""

    def __init__(self, message: str, code: str = "error", details: Optional[dict] = None):
        super().__init__(message)
        self.code = code
        self.details = details or {}


class Pacer:
    """Token bucket: ``rate`` permits per second, up to ``burst`` saved up."""

    def __init__(self, rate: float, burst: int):
        self.rate = rate
        self.burst = float(burst)
        self._tokens = float(burst)
        self._stamp = time.monotonic()
        self._lock = threading.Lock()

    def wait_turn(self) -> float:
        """Block until a permit is free; returns the time waited."""
        if self.rate <= 0:
            return 0.0
        with self._lock:
            now = time.monotonic()
            self._tokens = min(self.burst, self._tokens + (now - self._stamp) * self.rate)
            self._stamp = now
            if self._tokens >= 1.0:
                self._tokens -= 1.0
                return 0.0
            delay = (1.0 - self._tokens) / self.rate
            self._tokens = 0.0
            self._stamp = now + delay
        time.sleep(delay)
        return delay


class LiveLink:
    def __init__(self, host: Optional[str] = None, port: Optional[int] = None):
        self.host = host or os.environ.get("ABLETON_MCP_HOST", DEFAULT_HOST)
        self.port = int(port or os.environ.get("ABLETON_MCP_PORT", DEFAULT_PORT))
        self.default_timeout = float(os.environ.get("ABLETON_MCP_TIMEOUT", "20"))
        self._sock: Optional[socket.socket] = None
        self._lock = threading.RLock()
        self._decoder = json.JSONDecoder()
        self._register: Dict[str, dict] = {}
        # Set by the tool wrapper for the duration of one tool call:
        self.confirmed = False          # the user agreed to a destructive tool
        self.journal: Optional[list] = None   # collects journal entries of replies
        self._pacer = Pacer(
            rate=float(os.environ.get("ABLETON_MCP_EDIT_RATE", "5")),
            burst=int(os.environ.get("ABLETON_MCP_EDIT_BURST", "8")),
        )

    # -- public ------------------------------------------------------------

    def call(self, command: str, **params: Any) -> Any:
        """Run one bridge command and return its result."""
        with self._lock:
            if self._sock is None:
                self._open()
            spec = self._register.get(command)
            if spec is None or spec.get("zone") != "read":
                self._pacer.wait_turn()
            timeout = (spec["timeout_s"] + _GRACE) if spec else self.default_timeout
            try:
                reply = self._exchange(command, params, timeout)
            except _Stale:
                # The peer closed the connection while idle (Live restarted,
                # script reloaded). Nothing was executed; one fresh attempt.
                self._drop()
                self._open()
                reply = self._exchange(command, params, timeout)
        if reply.get("status") == "error":
            raise LiveError(
                str(reply.get("message", "unknown error")),
                str(reply.get("code", "error")),
                reply.get("details"),
            )
        result = reply.get("result", {})
        if self.journal is not None and isinstance(result, dict):
            self.journal.extend(result.get("journal") or [])
        return result

    def commands(self) -> Dict[str, dict]:
        """The bridge's command register as fetched at connect time."""
        with self._lock:
            if self._sock is None:
                self._open()
            return dict(self._register)

    def close(self) -> None:
        with self._lock:
            self._drop()

    @property
    def connected(self) -> bool:
        return self._sock is not None

    # -- internals ---------------------------------------------------------

    def _open(self) -> None:
        try:
            sock = socket.create_connection((self.host, self.port), timeout=3.0)
        except OSError as problem:
            raise LiveError(
                f"cannot reach the Remote Script on {self.host}:{self.port} ({problem}). "
                "Is Ableton Live running with the AbletonMCP control surface selected?",
                code="not_connected",
            )
        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        self._sock = sock
        self._register = {}
        try:
            listing = self._exchange("list_commands", {}, self.default_timeout)
            if listing.get("status") == "success":
                for entry in listing["result"].get("commands", []):
                    self._register[entry["name"]] = entry
        except (LiveError, _Stale, KeyError, TypeError):
            # An older script without a register still works; it just gets
            # default timeouts and pacing for everything.
            self._register = {}
        log.info("connected to Live on %s:%d (%d commands)",
                 self.host, self.port, len(self._register))

    def _drop(self) -> None:
        if self._sock is not None:
            try:
                self._sock.close()
            except OSError:
                pass
        self._sock = None

    def _peer_gone(self) -> bool:
        """True if the idle socket has been closed by the other side."""
        readable, _w, _x = select.select([self._sock], [], [], 0)
        if not readable:
            return False
        try:
            return self._sock.recv(1, socket.MSG_PEEK) == b""
        except OSError:
            return True

    def _exchange(self, command: str, params: dict, timeout: float) -> dict:
        assert self._sock is not None
        if self._peer_gone():
            raise _Stale()
        envelope = {"type": command, "params": params}
        if self.confirmed:
            envelope["confirm"] = True
        payload = json.dumps(envelope).encode("utf-8")
        try:
            self._sock.settimeout(timeout)
            self._sock.sendall(payload)
            return self._read_reply(timeout)
        except socket.timeout:
            self._drop()
            raise LiveError(
                f"no reply to '{command}' within {timeout:.0f} s. Live may be busy "
                "or showing a dialog; the command may still complete.",
                code="timeout",
            )
        except OSError as problem:
            self._drop()
            raise LiveError(f"connection to Live lost during '{command}': {problem}",
                            code="connection_lost")

    def _read_reply(self, timeout: float) -> dict:
        deadline = time.monotonic() + timeout
        pieces = []
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise socket.timeout()
            self._sock.settimeout(remaining)
            chunk = self._sock.recv(262144)
            if not chunk:
                raise OSError("connection closed by Live")
            pieces.append(chunk)
            if b"}" not in chunk:
                continue
            try:
                text = b"".join(pieces).decode("utf-8")
                reply, _end = self._decoder.raw_decode(text.lstrip())
            except (UnicodeDecodeError, ValueError):
                continue  # reply not complete yet
            if not isinstance(reply, dict):
                raise OSError("malformed reply from Live")
            return reply


class _Stale(Exception):
    """Internal: the connection was found dead before anything was sent."""
