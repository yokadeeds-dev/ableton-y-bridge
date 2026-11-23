"""TCP side of the bridge: listener, per-client sessions, message framing.

Wire format (unchanged for compatibility with existing clients):

* request  ``{"type": "<command>", "params": {...}}``
* reply    ``{"status": "success", "result": ...}`` or
           ``{"status": "error", "message": "...", "code": "..."}``

Messages are bare JSON objects without a length prefix or delimiter, so the
receiver has to find the end of each object itself. `StreamDecoder` does
that incrementally and copes with objects split over several packets, with
several objects in one packet and with whitespace or newlines in between.
"""

import codecs
import json
import socket
import sys
import threading
import time


class FramingError(Exception):
    """The byte stream cannot be a sequence of JSON objects."""


class StreamDecoder(object):
    def __init__(self, limit):
        self._limit = limit
        self._utf8 = codecs.getincrementaldecoder("utf-8")("strict")
        self._json = json.JSONDecoder()
        self._held = ""

    def feed(self, chunk):
        """Add received bytes, return the list of messages completed by them."""
        try:
            fresh = self._utf8.decode(chunk)
        except UnicodeDecodeError:
            raise FramingError("request is not valid UTF-8")
        self._held += fresh
        # An object can only have ended if a closing brace arrived.
        if "}" not in fresh:
            self._check_size()
            return []
        messages = []
        while True:
            text = self._held.lstrip()
            if not text:
                self._held = ""
                break
            if text[0] != "{":
                self._held = ""
                raise FramingError("a request must be a JSON object")
            try:
                message, end = self._json.raw_decode(text)
            except ValueError:
                self._held = text
                self._check_size()
                break
            messages.append(message)
            self._held = text[end:]
        return messages

    def _check_size(self):
        if len(self._held) > self._limit:
            self._held = ""
            raise FramingError("request exceeds %d bytes" % self._limit)


def encode_reply(reply):
    return json.dumps(reply, default=str).encode("utf-8")


class Listener(object):
    """Accepts clients and answers their requests through `answer`.

    ``answer(message)`` is called on the client's own thread and must return
    the reply dict; it is expected to block until Live has done the work.
    """

    def __init__(self, host, port, answer, log, max_request):
        self._host = host
        self._port = port
        self._answer = answer
        self._log = log
        self._max_request = max_request
        self._server = None
        self._clients = set()
        self._clients_lock = threading.Lock()
        self._alive = False
        self._thread = None
        self.bound = False

    def start(self):
        self._alive = True
        self._thread = threading.Thread(target=self._run, name="bridge-listener")
        self._thread.daemon = True
        self._thread.start()

    def stop(self):
        self._alive = False
        server, self._server = self._server, None
        if server is not None:
            _close_quietly(server)
        with self._clients_lock:
            clients = list(self._clients)
            self._clients.clear()
        for client in clients:
            _close_quietly(client)
        if self._thread is not None and self._thread is not threading.current_thread():
            self._thread.join(1.5)

    def client_count(self):
        with self._clients_lock:
            return len(self._clients)

    # -- internals ---------------------------------------------------------

    def _open_server(self):
        server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        if not sys.platform.startswith("win"):
            # On Windows SO_REUSEADDR would let a second listener share the
            # port silently; there a plain bind is the safe choice.
            server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind((self._host, self._port))
        server.listen(8)
        server.settimeout(0.5)
        return server

    def _run(self):
        # A predecessor (script toggled in Live's preferences) may need a
        # moment to let go of the port.
        attempt = 0
        while self._alive and self._server is None:
            attempt += 1
            try:
                self._server = self._open_server()
                self.bound = True
                self._log("bridge listening on %s:%d" % (self._host, self._port))
            except OSError as problem:
                if attempt == 1 or attempt % 10 == 0:
                    self._log("cannot bind %s:%d yet (%s), retrying"
                              % (self._host, self._port, problem))
                if attempt >= 60:
                    self._log("giving up on port %d" % self._port)
                    return
                time.sleep(0.5)
        while self._alive:
            server = self._server
            if server is None:
                break
            try:
                client, peer = server.accept()
            except socket.timeout:
                continue
            except OSError:
                if self._alive:
                    time.sleep(0.2)
                continue
            with self._clients_lock:
                self._clients.add(client)
            worker = threading.Thread(
                target=self._serve, args=(client, peer), name="bridge-client"
            )
            worker.daemon = True
            worker.start()

    def _serve(self, client, peer):
        decoder = StreamDecoder(self._max_request)
        try:
            client.settimeout(None)
            while self._alive:
                chunk = client.recv(65536)
                if not chunk:
                    break
                try:
                    messages = decoder.feed(chunk)
                except FramingError as problem:
                    client.sendall(encode_reply(
                        {"status": "error", "code": "bad_request", "message": str(problem)}
                    ))
                    break
                for message in messages:
                    client.sendall(encode_reply(self._answer(message)))
        except OSError:
            pass  # client went away; nothing to report
        except Exception as problem:  # never let a client thread die silently
            self._log("client %s: %r" % (peer, problem))
        finally:
            with self._clients_lock:
                self._clients.discard(client)
            _close_quietly(client)


def _close_quietly(sock):
    try:
        sock.shutdown(socket.SHUT_RDWR)
    except OSError:
        pass
    try:
        sock.close()
    except OSError:
        pass
