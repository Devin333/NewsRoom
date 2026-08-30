from __future__ import annotations

from backend.foundation.policies.base_policy import BasePolicy


class ConfidencePolicy(BasePolicy):
    minimum_display_confidence: float = 0.5
    minimum_relation_confidence: float = 0.5
    minimum_insight_confidence: float = 0.55
    minimum_output_confidence: float = 0.5

    def display_level(self, value: float) -> str:
        confidence = float(value)
        if confidence < 0.5:
            return "hidden"
        if confidence < 0.7:
            return "weak_related"
        if confidence < 0.9:
            return "related"
        return "strong_related"

    def can_display(self, value: float) -> bool:
        return float(value) >= self.minimum_display_confidence


__all__ = ["ConfidencePolicy"]
