from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from framework.shared.errors import ValidationError


@dataclass(frozen=True)
class ResourcePolicy:
    max_cpu_units: float | None = None
    max_memory_mb: float | None = None
    max_runtime_seconds: float | None = None

    def __post_init__(self) -> None:
        for name, value in (
            ("max_cpu_units", self.max_cpu_units),
            ("max_memory_mb", self.max_memory_mb),
            ("max_runtime_seconds", self.max_runtime_seconds),
        ):
            if value is not None and value < 0:
                raise ValidationError(f"{name} must be non-negative", code="invalid_resource_limit")

    def check_cpu(self, estimate: Any) -> list[str]:
        return _check_limit(
            label="cpu units",
            limit=self.max_cpu_units,
            actual=_extract_number(estimate, ("cpu_units", "cpu", "units")),
        )

    def check_memory(self, estimate: Any) -> list[str]:
        return _check_limit(
            label="memory MB",
            limit=self.max_memory_mb,
            actual=_extract_number(estimate, ("memory_mb", "memory", "mb")),
        )

    def check_runtime(self, estimate: Any) -> list[str]:
        return _check_limit(
            label="runtime seconds",
            limit=self.max_runtime_seconds,
            actual=_extract_number(estimate, ("runtime_seconds", "runtime", "seconds")),
        )


def _check_limit(*, label: str, limit: float | None, actual: float | None) -> list[str]:
    if limit is None or actual is None or actual <= limit:
        return []
    return [f"{label} estimate {actual:g} exceeds limit {limit:g}"]


def _extract_number(estimate: Any, names: tuple[str, ...]) -> float | None:
    if isinstance(estimate, (int, float)):
        return float(estimate)
    if isinstance(estimate, dict):
        for name in names:
            value = estimate.get(name)
            if isinstance(value, (int, float)):
                return float(value)
    for name in names:
        value = getattr(estimate, name, None)
        if isinstance(value, (int, float)):
            return float(value)
    return None
