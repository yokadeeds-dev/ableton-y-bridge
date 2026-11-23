#!/usr/bin/env python3
# Copyright (C) 2026 Yoka
# SPDX-License-Identifier: AGPL-3.0-only
"""
Real-time audio analyzer for Ableton Live
Captures system audio via WASAPI loopback (pyaudiowpatch),
performs spectral analysis, and sends metrics via UDP to localhost:7878
"""

import os
import numpy as np
import pyaudiowpatch as pyaudio
import json
import socket
import threading
import time
from scipy import signal
from datetime import datetime
import pyloudnorm as pyln
import logging
import sys

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'audio_analyzer.log'), encoding='utf-8')
    ]
)
logger = logging.getLogger(__name__)

CHUNK = 2048
FORMAT = pyaudio.paFloat32
UDP_HOST = 'localhost'
UDP_PORT = 7878
UPDATE_INTERVAL = 0.2  # seconds between UDP sends
CACHE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'analyzer_cache.json')


class AudioAnalyzer:
    def __init__(self):
        self.pa = pyaudio.PyAudio()
        self.sample_rate = 44100
        self.channels = 2

        # 2-second rolling buffer (mono mix)
        self.buffer_len = self.sample_rate * 2
        self.audio_buffer = np.zeros(self.buffer_len, dtype=np.float32)
        self.buffer_index = 0
        self.buffer_lock = threading.Lock()

        # Peak hold
        self.peak_level = 0.0
        self.peak_ts = 0.0
        self.peak_hold = 1.0

        # LUFS meter
        self.meter = pyln.Meter(self.sample_rate)

        # UDP socket
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

        self.running = False
        self.stream = None

        # Frequency bands
        self.bands = {
            'sub':  (20,   60),
            'low':  (60,   250),
            'mid':  (250,  2000),
            'high': (2000, 8000),
            'air':  (8000, 20000),
        }
        self.filters = {}
        self._build_filters()

    def _build_filters(self):
        nyq = self.sample_rate / 2
        for name, (lo, hi) in self.bands.items():
            try:
                b, a = signal.butter(2, [lo / nyq, min(hi / nyq, 0.99)], btype='band')
                self.filters[name] = (b, a)
            except Exception as e:
                logger.warning(f"Filter build failed for {name}: {e}")

    @staticmethod
    def _device_name_filter():
        """``audio.device_name_filter`` from config.json next to this script ('' = none)."""
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'config.json')
        try:
            with open(path, encoding='utf-8') as handle:
                return str(json.load(handle).get('audio', {}).get('device_name_filter', '')).strip().lower()
        except (OSError, ValueError):
            return ''

    def _find_loopback_device(self):
        """
        Find the WASAPI loopback device to measure.
        A device whose name contains ``audio.device_name_filter`` from config.json
        is preferred (for example the name of your audio interface); otherwise the
        first loopback device, normally the Windows default output, is used.
        """
        logger.info("Scanning for WASAPI loopback devices...")
        wanted = self._device_name_filter()
        matching_loopback = None
        default_loopback = None

        try:
            for loopback in self.pa.get_loopback_device_info_generator():
                name = loopback['name'].lower()
                logger.info(f"  Loopback device: [{loopback['index']}] {loopback['name']} "
                            f"(ch={loopback['maxInputChannels']}, sr={int(loopback['defaultSampleRate'])})")
                if wanted and matching_loopback is None and wanted in name:
                    matching_loopback = loopback
                if default_loopback is None:
                    default_loopback = loopback
        except AttributeError:
            raise RuntimeError(
                "pyaudiowpatch does not support get_loopback_device_info_generator(). "
                "Make sure pyaudiowpatch (not pyaudio) is installed."
            )

        if matching_loopback:
            logger.info(f"Using loopback matching '{wanted}': "
                        f"[{matching_loopback['index']}] {matching_loopback['name']}")
            return matching_loopback
        if wanted:
            logger.warning(f"No loopback device matches '{wanted}'; using the default.")
        if default_loopback:
            logger.info(f"Using default loopback: [{default_loopback['index']}] {default_loopback['name']}")
            return default_loopback
        else:
            raise RuntimeError(
                "No WASAPI loopback device found. "
                "Make sure pyaudiowpatch is installed and an audio output device is active."
            )

    def _callback(self, in_data, frame_count, time_info, status):
        audio = np.frombuffer(in_data, dtype=np.float32).copy()

        # Mix to mono if stereo
        if self.channels > 1:
            audio = audio.reshape(-1, self.channels).mean(axis=1)

        with self.buffer_lock:
            end = self.buffer_index + len(audio)
            if end <= self.buffer_len:
                self.audio_buffer[self.buffer_index:end] = audio
            else:
                # Wrap around
                first = self.buffer_len - self.buffer_index
                self.audio_buffer[self.buffer_index:] = audio[:first]
                self.audio_buffer[:end - self.buffer_len] = audio[first:]
            self.buffer_index = end % self.buffer_len

        peak = float(np.max(np.abs(audio)))
        now = time.time()
        if peak > self.peak_level or now - self.peak_ts > self.peak_hold:
            self.peak_level = peak
            self.peak_ts = now

        return (None, pyaudio.paContinue)

    def start(self):
        try:
            device = self._find_loopback_device()
        except RuntimeError as e:
            logger.error(f"Cannot start audio analyzer: {e}")
            cached = AudioAnalyzer.load_cache()
            if cached:
                logger.warning("Offline-Fallback: sende letzten bekannten Cache via UDP.")
                self.running = True
                t = threading.Thread(target=self._offline_replay_loop, args=(cached,), daemon=True)
                t.start()
            else:
                logger.error("Kein Cache vorhanden — UDP metrics werden nicht gesendet.")
            return
        self.sample_rate = int(device['defaultSampleRate'])
        self.channels = device['maxInputChannels']

        # Rebuild buffer and meter at correct sample rate
        self.buffer_len = self.sample_rate * 2
        self.audio_buffer = np.zeros(self.buffer_len, dtype=np.float32)
        self.meter = pyln.Meter(self.sample_rate)
        self._build_filters()

        logger.info(f"Opening stream: device={device['index']}, sr={self.sample_rate}, ch={self.channels}")

        self.stream = self.pa.open(
            format=FORMAT,
            channels=self.channels,
            rate=self.sample_rate,
            frames_per_buffer=CHUNK,
            input=True,
            input_device_index=device['index'],
            stream_callback=self._callback
        )
        self.running = True
        self.stream.start_stream()

        t = threading.Thread(target=self._send_loop, daemon=True)
        t.start()
        logger.info("Audio analyzer running — sending UDP to localhost:7878")

    def stop(self):
        self.running = False
        if self.stream:
            self.stream.stop_stream()
            self.stream.close()
        self.pa.terminate()
        self.sock.close()

    def _rms_db(self, data):
        rms = np.sqrt(np.mean(data ** 2))
        return 20 * np.log10(rms) if rms > 1e-10 else -999.0

    def _peak_db(self):
        return 20 * np.log10(self.peak_level) if self.peak_level > 1e-10 else -999.0

    def _lufs(self, data):
        try:
            data = np.clip(data, -1.0, 1.0)
            v = self.meter.integrated_loudness(data)
            if v is not None and not np.isnan(v) and not np.isinf(v):
                return float(v)
        except Exception:
            pass
        return -999.0

    def _band_rms(self, data, name):
        if name not in self.filters:
            return -999.0
        try:
            b, a = self.filters[name]
            filtered = signal.filtfilt(b, a, data)
            return round(self._rms_db(filtered), 1)
        except Exception:
            return -999.0

    def _write_cache(self, msg: dict):
        """Schreibt den letzten bekannten Analyzer-Zustand in eine JSON-Cache-Datei."""
        try:
            with open(CACHE_PATH, 'w', encoding='utf-8') as f:
                json.dump(msg, f)
        except OSError as e:
            logger.warning(f"Cache write failed: {e}")

    @staticmethod
    def load_cache() -> dict:
        """Lädt den letzten bekannten Analyzer-Zustand aus dem Cache (falls vorhanden)."""
        try:
            with open(CACHE_PATH, 'r', encoding='utf-8') as f:
                return json.load(f)
        except (OSError, json.JSONDecodeError):
            return {}

    def _send_loop(self):
        logger.info("Send loop started")
        _cache_write_counter = 0
        while self.running:
            time.sleep(UPDATE_INTERVAL)
            try:
                with self.buffer_lock:
                    buf = self.audio_buffer.copy()

                msg = {
                    'timestamp': datetime.now().isoformat(),
                    'rms_db': round(self._rms_db(buf), 1),
                    'peak_db': round(self._peak_db(), 1),
                    'lufs_approx': round(self._lufs(buf), 1),
                    'bands': {n: self._band_rms(buf, n) for n in self.bands},
                }
                data = json.dumps(msg).encode()
                self.sock.sendto(data, (UDP_HOST, UDP_PORT))

                # Cache alle 5s schreiben (nicht bei jedem 200ms-Tick)
                _cache_write_counter += 1
                if _cache_write_counter >= 25:
                    self._write_cache(msg)
                    _cache_write_counter = 0

                # Alle 10s Buffer-Sample loggen (Debug)
                if int(time.time()) % 10 == 0:
                    sample = buf[::1000][:5]
                    logger.info(f"Buffer sample (max={np.max(np.abs(buf)):.6f}): {sample}")
                logger.debug(f"UDP sent: {msg}")
            except Exception as e:
                logger.error(f"Send loop error: {e}")
        logger.info("Send loop stopped")

    def _offline_replay_loop(self, cached: dict):
        """Sendet gecachte Werte via UDP wenn kein Live-Device verfügbar ist."""
        logger.info("Offline-Modus: sende gecachte Analyzer-Daten (statisch)")
        data = json.dumps({**cached, "offline": True}).encode()
        while self.running:
            try:
                self.sock.sendto(data, (UDP_HOST, UDP_PORT))
            except OSError:
                pass
            time.sleep(UPDATE_INTERVAL)


def main():
    logger.info("=" * 60)
    logger.info("Audio Analyzer (pyaudiowpatch WASAPI loopback)")
    logger.info("=" * 60)

    analyzer = AudioAnalyzer()
    try:
        analyzer.start()
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        logger.info("Stopping...")
    except Exception as e:
        logger.error(f"Fatal: {e}")
        raise
    finally:
        analyzer.stop()
        logger.info("Stopped.")


if __name__ == '__main__':
    main()
