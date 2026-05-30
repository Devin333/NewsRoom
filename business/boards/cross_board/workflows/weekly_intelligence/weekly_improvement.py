from __future__ import annotations

from datetime import datetime, timezone as _tz
UTC = _tz.utc
from hashlib import sha1
from typing import Any


class WeeklyImprovementBuilder:
    def build(self, weekly_quality: dict[str, Any], weekly_trends: dict[str, Any]) -> dict[str, Any]:
        recommendations = []
        for weak_spot in weekly_quality.get("weak_spots") or []:
            recommendations.append(
                {
                    "recommendation_id": _stable_id("weekly", weak_spot),
                    "source": "weekly_quality",
                    "board_type": "weekly_intelligence",
                    "target_type": "board_quality_gate_override",
                    "target_id": str(weak_spot),
                    "severity": "warning",
                    "reason": f"Weekly quality weak spot: {weak_spot}",
                    "suggested_action": "Review source coverage and trend confidence thresholds.",
                    "evidence": [{"weak_spot": weak_spot}],
                    "created_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
                }
            )
        if not recommendations and weekly_trends.get("weak_signal_trends"):
            recommendations.append(
                {
                    "recommendation_id": _stable_id("weekly", "weak_signal_review"),
                    "source": "weekly_trend_analysis",
                    "board_type": "weekly_intelligence",
                    "target_type": "skill_prompt_hint_override",
                    "target_id": "trend-analysis",
                    "severity": "info",
                    "reason": "Weekly run produced weak-signal trends that may need analyst review.",
                    "suggested_action": "Add review hints for weak-signal trend synthesis.",
                    "evidence": list(weekly_trends.get("weak_signal_trends") or []),
                    "created_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
                }
            )
        return {
            "recommendations": recommendations,
            "risks": ["manual approval required before overrides"] if recommendations else [],
            "next_actions": ["review weekly recommendations"] if recommendations else ["continue monitoring"],
        }


def _stable_id(prefix: str, value: str) -> str:
    return f"{prefix}_{sha1(value.encode('utf-8')).hexdigest()[:12]}"


__all__ = ["WeeklyImprovementBuilder"]
