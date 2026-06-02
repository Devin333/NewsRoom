"""Metric helpers for benchmark extraction."""

from __future__ import annotations


def normalize_metric_value(value: float | int, unit: str | None) -> float:
    """Normalize percentage-like metric values into 0..1 range."""

    numeric = float(value)
    if unit in {"%", "percent"} or numeric > 1.0:
        return round(numeric / 100.0, 4)
    return round(numeric, 4)
