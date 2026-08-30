from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class ImprovementMeasurement:
    quality_score_delta: float | None
    card_count_delta: int
    evidence_coverage_delta: float | None
    duplicate_rate_delta: float | None
    empty_output_delta: int
    subscription_match_delta: float | None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class ImprovementMeasurementBuilder:
    def measure(self, before: dict[str, Any] | None, after: dict[str, Any]) -> ImprovementMeasurement:
        before = before or {}
        return ImprovementMeasurement(
            quality_score_delta=_delta_float(before.get("quality_score"), after.get("quality_score")),
            card_count_delta=int(after.get("card_count") or 0) - int(before.get("card_count") or 0),
            evidence_coverage_delta=_delta_float(before.get("evidence_coverage"), after.get("evidence_coverage")),
            duplicate_rate_delta=_delta_float(before.get("duplicate_rate"), after.get("duplicate_rate")),
            empty_output_delta=int(bool(after.get("empty_output"))) - int(bool(before.get("empty_output"))),
            subscription_match_delta=_delta_float(before.get("subscription_match"), after.get("subscription_match")),
        )


def _delta_float(before: Any, after: Any) -> float | None:
    if before is None or after is None:
        return None
    try:
        return round(float(after) - float(before), 4)
    except (TypeError, ValueError):
        return None


__all__ = ["ImprovementMeasurement", "ImprovementMeasurementBuilder"]
