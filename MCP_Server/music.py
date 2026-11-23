# Copyright (C) 2026 Yoka
# SPDX-License-Identifier: AGPL-3.0-only
"""Small music-theory helpers used by the tools: rhythm, key, curve shapes."""

from __future__ import annotations

import math
from typing import Callable, Dict, List, Sequence, Tuple

NOTE_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]

# Krumhansl & Kessler (1982) probe-tone ratings, index 0 = tonic.
KK_MAJOR = (6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88)
KK_MINOR = (6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17)

MAJOR_SCALE = (0, 2, 4, 5, 7, 9, 11)
MINOR_SCALE = (0, 2, 3, 5, 7, 8, 10)


# -- rhythm ----------------------------------------------------------------

def euclidean_pattern(steps: int, pulses: int, rotation: int = 0) -> List[int]:
    """`pulses` hits spread as evenly as possible over `steps` slots.

    Slot i gets a hit when the running sum i*pulses wraps past a multiple of
    `steps` (the same idea as drawing a straight line on a pixel grid). The
    pattern starts with a hit; `rotation` shifts it left.
    """
    if steps <= 0:
        return []
    pattern = [1 if (slot * pulses) % steps < pulses else 0 for slot in range(steps)]
    shift = rotation % steps
    return pattern[shift:] + pattern[:shift]


# -- key estimation ----------------------------------------------------------

def pitch_class_weights(notes: Sequence[dict]) -> List[float]:
    """Share of each pitch class, weighting notes by duration and velocity."""
    weights = [0.0] * 12
    for note in notes:
        weight = float(note.get("duration", 0.25)) * float(note.get("velocity", 100)) / 127.0
        weights[int(note.get("pitch", 60)) % 12] += weight
    total = sum(weights)
    return [w / total for w in weights] if total else weights


def _correlation(xs: Sequence[float], ys: Sequence[float]) -> float:
    count = len(xs)
    mean_x, mean_y = sum(xs) / count, sum(ys) / count
    spread_x = math.sqrt(sum((x - mean_x) ** 2 for x in xs))
    spread_y = math.sqrt(sum((y - mean_y) ** 2 for y in ys))
    if spread_x == 0 or spread_y == 0:
        return 0.0
    return sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys)) / (spread_x * spread_y)


def rank_keys(weights: Sequence[float]) -> List[Tuple[str, float]]:
    """All 24 keys with their profile correlation, best first."""
    ranking = []
    for tonic in range(12):
        seen_from_tonic = list(weights[tonic:]) + list(weights[:tonic])
        ranking.append((f"{NOTE_NAMES[tonic]} major",
                        round(_correlation(seen_from_tonic, KK_MAJOR), 4)))
        ranking.append((f"{NOTE_NAMES[tonic]} minor",
                        round(_correlation(seen_from_tonic, KK_MINOR), 4)))
    ranking.sort(key=lambda entry: entry[1], reverse=True)
    return ranking


def key_by_scale_fit(counts: Sequence[int]) -> str:
    """Key whose scale covers most of the notes (plain counts, no weighting)."""
    total = sum(counts)
    if not total:
        return "unknown"
    best_name, best_cover = "unknown", -1.0
    for tonic in range(12):
        for mode, scale in (("major", MAJOR_SCALE), ("minor", MINOR_SCALE)):
            cover = sum(counts[(tonic + degree) % 12] for degree in scale) / total
            if cover > best_cover:
                best_name, best_cover = f"{NOTE_NAMES[tonic]} {mode}", cover
    return best_name


# -- curve shapes ------------------------------------------------------------
# Each shape maps (progress 0..1 over the whole span, phase 0..1 within the
# current cycle, number of cycles) to a value 0..1.

def _noise(progress: float) -> float:
    """Repeatable pseudo-random value for a position (no global RNG state)."""
    state = (int(progress * 9973) * 2654435761 + 40503) & 0xFFFFFFFF
    state ^= state >> 15
    return (state & 0xFFFF) / 65535.0


def _envelope(progress: float) -> float:
    """Rise in the first fifth, fall to 0.7, hold, release in the last fifth."""
    if progress < 0.2:
        return progress / 0.2
    if progress < 0.5:
        return 1.0 - 0.3 * (progress - 0.2) / 0.3
    if progress < 0.8:
        return 0.7
    return 0.7 * (1.0 - progress) / 0.2


CURVES: Dict[str, Callable[[float, float, float], float]] = {
    "sine": lambda progress, phase, cycles: 0.5 - 0.5 * math.cos(2 * math.pi * phase),
    "cosine": lambda progress, phase, cycles: 0.5 + 0.5 * math.cos(2 * math.pi * phase),
    "triangle": lambda progress, phase, cycles: 1.0 - abs(2.0 * phase - 1.0),
    "sawtooth": lambda progress, phase, cycles: phase,
    "reverse_saw": lambda progress, phase, cycles: 1.0 - phase,
    "square": lambda progress, phase, cycles: 1.0 if phase < 0.5 else 0.0,
    "exponential": lambda progress, phase, cycles: progress * progress,
    "logarithmic": lambda progress, phase, cycles: math.sqrt(progress),
    "s_curve": lambda progress, phase, cycles: progress * progress * (3.0 - 2.0 * progress),
    "random": lambda progress, phase, cycles: _noise(progress),
    "envelope": lambda progress, phase, cycles: _envelope(progress),
    "bounce": lambda progress, phase, cycles:
        abs(math.sin(math.pi * cycles * progress)) * (1.0 - progress),
}
