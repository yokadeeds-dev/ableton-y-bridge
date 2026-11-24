#!/usr/bin/env python3
# Copyright (C) 2026 Yoka
# SPDX-License-Identifier: AGPL-3.0-only
"""
Ableton MCP — Live Audio Dashboard
====================================
Leichtgewichtiges WebSocket-Dashboard das die UDP-Analyzer-Daten
in Echtzeit im Browser darstellt.

Starten: python dashboard.py
Öffnen:  http://localhost:8765
"""

import asyncio
import json
import socket
import threading
import time
import logging
from http.server import BaseHTTPRequestHandler, HTTPServer

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
logger = logging.getLogger("dashboard")

UDP_PORT = 7878
WS_PORT  = 8766   # WebSocket
HTTP_PORT = 8765  # Browser
HOST = '127.0.0.1'  # this computer only: page, WebSocket and UDP input are not for the network

# ─── Shared State ────────────────────────────────────────────────────────────

_latest: dict = {}
_lock = threading.Lock()
_ws_clients: set = set()
_ws_clients_lock = threading.Lock()

# ─── UDP → shared state ──────────────────────────────────────────────────────

def _udp_reader():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.settimeout(1.0)
    try:
        sock.bind((HOST, UDP_PORT))
        logger.info(f"UDP reader on :{UDP_PORT}")
    except OSError as e:
        logger.error(f"UDP bind failed: {e}")
        return
    while True:
        try:
            data, _ = sock.recvfrom(4096)
            payload = json.loads(data.decode('utf-8'))
            with _lock:
                _latest.update(payload)
        except socket.timeout:
            continue
        except (json.JSONDecodeError, OSError):
            continue

# ─── WebSocket Server (asyncio, kein extra Framework) ────────────────────────

async def _ws_handler(reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
    """Minimal WebSocket handshake + broadcast loop."""
    import base64, hashlib

    # HTTP Upgrade lesen
    raw = b""
    while b"\r\n\r\n" not in raw:
        chunk = await reader.read(1024)
        if not chunk:
            return
        raw += chunk

    headers = {}
    for line in raw.decode('latin-1').split('\r\n')[1:]:
        if ':' in line:
            k, _, v = line.partition(':')
            headers[k.strip().lower()] = v.strip()

    key = headers.get('sec-websocket-key', '')
    accept = base64.b64encode(
        hashlib.sha1((key + '258EAFA5-E914-47DA-95CA-C5AB0DC85B11').encode()).digest()
    ).decode()

    upgrade = (
        "HTTP/1.1 101 Switching Protocols\r\n"
        "Upgrade: websocket\r\n"
        "Connection: Upgrade\r\n"
        f"Sec-WebSocket-Accept: {accept}\r\n\r\n"
    )
    writer.write(upgrade.encode('latin-1'))
    await writer.drain()

    with _ws_clients_lock:
        _ws_clients.add(writer)
    logger.info(f"WebSocket client connected ({len(_ws_clients)} total)")

    try:
        while True:
            await asyncio.sleep(0.2)   # keepalive — client bleibt in set
            if writer.is_closing():
                break
    finally:
        with _ws_clients_lock:
            _ws_clients.discard(writer)
        logger.info("WebSocket client disconnected")


def _ws_encode(payload: str) -> bytes:
    """Encode a text frame (RFC 6455, no masking for server→client)."""
    b = payload.encode('utf-8')
    n = len(b)
    if n <= 125:
        return bytes([0x81, n]) + b
    elif n <= 65535:
        return bytes([0x81, 126, (n >> 8) & 0xFF, n & 0xFF]) + b
    else:
        return bytes([0x81, 127]) + n.to_bytes(8, 'big') + b


async def _broadcaster():
    """Sendet alle 200ms den aktuellen State an alle WebSocket-Clients."""
    while True:
        await asyncio.sleep(0.2)
        with _lock:
            snapshot = dict(_latest)
        if not snapshot:
            continue
        frame = _ws_encode(json.dumps(snapshot))
        dead = set()
        with _ws_clients_lock:
            clients = set(_ws_clients)
        for w in clients:
            try:
                w.write(frame)
                await w.drain()
            except (OSError, ConnectionResetError):
                dead.add(w)
        if dead:
            with _ws_clients_lock:
                _ws_clients.difference_update(dead)


async def _run_ws_server():
    server = await asyncio.start_server(_ws_handler, HOST, WS_PORT)
    logger.info(f"WebSocket server on ws://localhost:{WS_PORT}")
    async with server:
        await asyncio.gather(server.serve_forever(), _broadcaster())


# ─── HTTP Server — statisches Dashboard-HTML ─────────────────────────────────

_HTML = f"""<!DOCTYPE html>
<html lang="de">
<head>
<meta charset="UTF-8">
<title>Ableton MCP — Live Analyzer</title>
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ background: #141414; color: #e0e0e0; font-family: 'Courier New', monospace;
          display: flex; flex-direction: column; align-items: center; padding: 24px; }}
  h1 {{ font-size: 1.2rem; color: #888; margin-bottom: 20px; letter-spacing: 3px; }}
  .grid {{ display: grid; grid-template-columns: repeat(3, 1fr); gap: 16px; width: 100%; max-width: 900px; }}
  .card {{ background: #1e1e1e; border-radius: 8px; padding: 16px; }}
  .card h2 {{ font-size: 0.75rem; color: #666; text-transform: uppercase; letter-spacing: 2px; margin-bottom: 12px; }}
  .value {{ font-size: 2.4rem; font-weight: bold; color: #fff; }}
  .unit  {{ font-size: 0.8rem; color: #555; margin-left: 4px; }}
  .bars  {{ width: 100%; }}
  .bar-row {{ display: flex; align-items: center; margin-bottom: 8px; }}
  .bar-label {{ width: 36px; font-size: 0.7rem; color: #666; }}
  .bar-bg {{ flex: 1; background: #2a2a2a; border-radius: 3px; height: 14px; overflow: hidden; }}
  .bar-fill {{ height: 100%; border-radius: 3px; transition: width 0.18s ease; }}
  .bar-val {{ width: 52px; text-align: right; font-size: 0.7rem; color: #888; }}
  .status {{ font-size: 0.7rem; color: #444; margin-top: 20px; }}
  .online {{ color: #00c840; }} .offline {{ color: #ff4040; }}
</style>
</head>
<body>
<h1>ABLETON MCP — LIVE ANALYZER</h1>
<div class="grid">
  <div class="card">
    <h2>LUFS</h2>
    <span class="value" id="lufs">—</span><span class="unit">LUFS</span>
  </div>
  <div class="card">
    <h2>Peak</h2>
    <span class="value" id="peak">—</span><span class="unit">dBFS</span>
  </div>
  <div class="card">
    <h2>RMS</h2>
    <span class="value" id="rms">—</span><span class="unit">dB</span>
  </div>
  <div class="card" style="grid-column: span 3;">
    <h2>Spektrum</h2>
    <div class="bars" id="bars"></div>
  </div>
</div>
<div class="status">
  <span id="conn" class="offline">● Verbinde…</span>
  &nbsp;|&nbsp; <span id="ts">—</span>
</div>
<script>
const BAND_COLORS = {{
  sub: '#1A3CFF', low: '#FF6400', mid: '#00C840', high: '#FFD000', air: '#00DCFF'
}};
const BAND_ORDER = ['sub','low','mid','high','air'];
const BAND_LABELS = {{sub:'SUB',low:'LOW',mid:'MID',high:'HIGH',air:'AIR'}};

function dbToWidth(db) {{
  // -60 dB = 0%, 0 dB = 100%
  return Math.max(0, Math.min(100, ((db + 60) / 60) * 100));
}}

function initBars() {{
  const c = document.getElementById('bars');
  c.innerHTML = '';
  for (const b of BAND_ORDER) {{
    c.innerHTML += `<div class="bar-row">
      <div class="bar-label">${{BAND_LABELS[b]}}</div>
      <div class="bar-bg"><div class="bar-fill" id="bar_${{b}}" style="background:${{BAND_COLORS[b]}};width:0%"></div></div>
      <div class="bar-val" id="bv_${{b}}">—</div>
    </div>`;
  }}
}}
initBars();

const ws = new WebSocket('ws://localhost:{WS_PORT}');
ws.onopen  = () => document.getElementById('conn').className = 'online',
             document.getElementById('conn').textContent = '● Live';
ws.onclose = () => {{ document.getElementById('conn').className = 'offline';
                      document.getElementById('conn').textContent = '● Getrennt'; }};
ws.onmessage = (e) => {{
  const d = JSON.parse(e.data);
  document.getElementById('lufs').textContent = d.lufs_approx?.toFixed(1) ?? '—';
  document.getElementById('peak').textContent = d.peak_db?.toFixed(1) ?? '—';
  document.getElementById('rms').textContent  = d.rms_db?.toFixed(1) ?? '—';
  document.getElementById('ts').textContent   = d.timestamp ? d.timestamp.slice(11,19) : '—';
  const bands = d.bands || {{}};
  for (const b of BAND_ORDER) {{
    const v = bands[b] ?? -999;
    document.getElementById('bar_' + b).style.width = dbToWidth(v) + '%';
    document.getElementById('bv_'  + b).textContent = v > -990 ? v.toFixed(1) + ' dB' : '—';
  }}
  if (d.offline) document.getElementById('conn').textContent = '● Offline-Cache';
}};
</script>
</body>
</html>
"""


class _DashboardHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.end_headers()
        self.wfile.write(_HTML.encode('utf-8'))

    def log_message(self, fmt, *args):
        pass  # HTTP-Logs unterdrücken


def _run_http():
    httpd = HTTPServer((HOST, HTTP_PORT), _DashboardHandler)
    logger.info(f"Dashboard: http://localhost:{HTTP_PORT}")
    httpd.serve_forever()


# ─── Main ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    # UDP-Reader in separatem Thread
    threading.Thread(target=_udp_reader, daemon=True, name="udp-reader").start()
    # HTTP-Server in separatem Thread
    threading.Thread(target=_run_http,   daemon=True, name="http-server").start()
    # WebSocket + Broadcaster im asyncio-Loop (Hauptthread)
    logger.info("Starte Ableton MCP Dashboard…")
    try:
        asyncio.run(_run_ws_server())
    except KeyboardInterrupt:
        logger.info("Dashboard beendet.")
