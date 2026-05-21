from __future__ import annotations

from typing import Any

from framework.scoring.core import ScoringResult, ScoringTarget
from framework.scoring.features import FeatureValue, FeatureVector


def target_from_dict(payload: dict[str, Any]) -> ScoringTarget:
    if "target_id" in payload and "target_type" in payload:
        return ScoringTarget.from_dict(payload)
    return ScoringTarget(
        target_id=str(payload.get("id") or payload.get("card_id") or payload.get("target_id")),
        target_type=str(payload.get("type") or payload.get("target_type") or "dict"),
        payload=dict(payload),
    )


def features_from_dict(payload: dict[str, Any], *, source: str | None = None) -> FeatureVector:
    if "values" in payload:
        return FeatureVector.from_dict(payload)
    values: dict[str, FeatureValue] = {}
    for name, value in payload.items():
        if isinstance(value, FeatureValue):
            values[str(name)] = value
        elif isinstance(value, dict) and "value" in value:
            feature_payload = {"name": str(name), **value}
            values[str(name)] = FeatureValue.from_dict(feature_payload)
        elif isinstance(value, (int, float)):
            values[str(name)] = FeatureValue(name=str(name), value=float(value), source=source)
    return FeatureVector(values=values)


def result_to_dict(result: ScoringResult) -> dict[str, Any]:
    return result.to_dict()
