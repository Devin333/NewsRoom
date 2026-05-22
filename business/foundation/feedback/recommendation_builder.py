from __future__ import annotations

from hashlib import sha1
from typing import Any

from business.foundation.feedback.improvement_recommendation import ImprovementRecommendation


class ImprovementRecommendationBuilder:
    def build_from_learning_signals(
        self,
        signals: list[Any],
        *,
        board_type: str,
        source: str = "learning_signal",
    ) -> list[ImprovementRecommendation]:
        recommendations: list[ImprovementRecommendation] = []
        for signal in signals:
            payload = _payload(signal)
            signal_type = str(payload.get("signal_type") or "quality_gap")
            target_layer = str(payload.get("target_layer") or "board")
            target_id = str(payload.get("suggested_policy_profile_id") or signal_type)
            severity = _severity(payload.get("severity_score"))
            recommendations.append(
                ImprovementRecommendation(
                    recommendation_id=_stable_id("rec", board_type, signal_type, target_id, payload.get("related_feedback_ids", [])),
                    source=source,
                    board_type=board_type,
                    target_type=_target_type(signal_type, target_layer),
                    target_id=target_id,
                    severity=severity,
                    reason=str(payload.get("description") or f"{signal_type} requires review."),
                    suggested_action=_suggested_action(signal_type),
                    evidence=[
                        {
                            "signal_id": payload.get("signal_id"),
                            "related_feedback_ids": payload.get("related_feedback_ids", []),
                            "frequency": payload.get("frequency", 1),
                            "severity_score": payload.get("severity_score", 0.0),
                        }
                    ],
                )
            )
        return recommendations

    def build_from_quality_summary(
        self,
        quality_summary: Any,
        *,
        board_type: str,
    ) -> list[ImprovementRecommendation]:
        if quality_summary is None:
            return []
        checks = getattr(quality_summary, "checks", None)
        if checks is None and isinstance(quality_summary, dict):
            checks = quality_summary.get("checks")
        recommendations: list[ImprovementRecommendation] = []
        for check in checks or []:
            payload = _payload(check)
            if payload.get("passed") is True:
                continue
            check_type = str(payload.get("check_type") or "quality_check")
            recommendations.append(
                ImprovementRecommendation(
                    recommendation_id=_stable_id("rec", board_type, check_type, payload.get("observed", {})),
                    source="quality_summary",
                    board_type=board_type,
                    target_type="board_quality_gate",
                    target_id=check_type,
                    severity=str(payload.get("severity") or "warning"),
                    reason=str(payload.get("reason") or f"{check_type} failed."),
                    suggested_action=_suggested_action(check_type),
                    evidence=[payload],
                )
            )
        return recommendations


def _payload(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    to_dict = getattr(value, "to_dict", None)
    if callable(to_dict):
        return to_dict()
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        return model_dump(mode="json")
    return {}


def _stable_id(prefix: str, *parts: Any) -> str:
    digest = sha1("|".join(str(part) for part in parts).encode("utf-8")).hexdigest()[:12]
    return f"{prefix}_{digest}"


def _severity(score: Any) -> str:
    try:
        numeric = float(score)
    except (TypeError, ValueError):
        numeric = 0.5
    if numeric >= 0.8:
        return "error"
    if numeric >= 0.5:
        return "warning"
    return "info"


def _target_type(signal_type: str, target_layer: str) -> str:
    if "ranking" in signal_type or "rank" in signal_type:
        return "ranking_weight_override"
    if "source" in signal_type:
        return "source_reliability_override"
    if "skill" in signal_type:
        return "skill_prompt_hint_override"
    if "quality" in target_layer or "gate" in signal_type:
        return "board_quality_gate_override"
    return "policy_threshold_override"


def _suggested_action(signal_type: str) -> str:
    if "duplicate" in signal_type:
        return "tighten duplicate threshold"
    if "evidence" in signal_type:
        return "raise evidence coverage requirement"
    if "card" in signal_type:
        return "adjust ranking weights for card quality"
    return "review policy threshold and ranking weights"


__all__ = ["ImprovementRecommendationBuilder"]
