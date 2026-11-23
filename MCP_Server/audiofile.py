"""Reading audio files on the server side (Live does not publish sample data)."""

from __future__ import annotations

import math
import os
from typing import Optional

_BLOCK = 1 << 18  # frames per read


def peak_db(path: str) -> Optional[float]:
    """Sample peak of an audio file in dBFS; None if the file is silent.

    Uses the `soundfile` package when it is installed (WAV, AIFF, FLAC,
    OGG, MP3) and falls back to the standard library for PCM WAV files.
    """
    if not os.path.isfile(path):
        raise ValueError(f"audio file not found: {path}")
    try:
        peak = _peak_with_soundfile(path)
    except ImportError:
        peak = _peak_with_wave(path)
    if peak <= 0.0:
        return None
    return 20.0 * math.log10(peak)


def _peak_with_soundfile(path: str) -> float:
    # Deliberately without numpy: on Windows `import numpy` blocks forever in
    # a process whose stdin pipe is being read by another thread, which is
    # exactly the situation of an MCP server on stdio.
    import array

    import soundfile

    peak = 0.0
    with soundfile.SoundFile(path) as handle:
        while True:
            raw = handle.buffer_read(_BLOCK, dtype="float32")
            if not len(raw):
                break
            block = array.array("f")
            block.frombytes(bytes(raw))
            peak = max(peak, max(block), -min(block))
    return peak


def _peak_with_wave(path: str) -> float:
    import array
    import wave

    try:
        handle = wave.open(path, "rb")
    except (wave.Error, EOFError) as problem:
        raise ValueError(
            f"cannot read {os.path.basename(path)} without the 'soundfile' package "
            f"({problem}); install it with: pip install soundfile"
        )
    with handle:
        width = handle.getsampwidth()
        if width not in (2, 4):
            raise ValueError("only 16- and 32-bit PCM WAV can be read without 'soundfile'")
        code, full_scale = ("h", 32768.0) if width == 2 else ("i", 2147483648.0)
        peak = 0
        while True:
            raw = handle.readframes(_BLOCK)
            if not raw:
                break
            samples = array.array(code)
            samples.frombytes(raw)
            peak = max(peak, max(samples), -min(samples))
    return peak / full_scale
