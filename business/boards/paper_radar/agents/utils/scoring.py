"""Scoring helpers for paper analysis agents."""

from __future__ import annotations


def clamp_score(value: float, *, minimum: float = 0.0, maximum: float = 1.0) -> float:
    """Clamp and round a confidence-like score."""

    return round(max(minimum, min(maximum, float(value))), 2)
