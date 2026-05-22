from __future__ import annotations

from typing import Any


class CrossBoardImprovementService:
    def aggregate(self, board_payloads: dict[str, dict[str, Any]]) -> dict[str, Any]:
        recommendations: list[dict[str, Any]] = []
        reports: list[dict[str, Any]] = []
        for board_type, payload in board_payloads.items():
            for recommendation in payload.get("improvement_recommendations") or []:
                if isinstance(recommendation, dict):
                    recommendations.append({"board_type": board_type, **recommendation})
            report = payload.get("self_improvement_report")
            if isinstance(report, dict):
                reports.append({"board_type": board_type, **report})
        recommendations.sort(key=_recommendation_sort_key)
        return {
            "recommendations": recommendations,
            "reports": reports,
            "priority_order": [
                item.get("recommendation_id")
                for item in recommendations
                if item.get("recommendation_id")
            ],
            "next_actions": _next_actions(recommendations),
        }


def _recommendation_sort_key(item: dict[str, Any]) -> tuple[int, str]:
    severity_rank = {"block": 0, "error": 1, "warning": 2, "info": 3}
    return severity_rank.get(str(item.get("severity")), 4), str(item.get("recommendation_id") or "")


def _next_actions(recommendations: list[dict[str, Any]]) -> list[str]:
    if not recommendations:
        return ["continue monitoring"]
    return ["review highest-severity board proposals", "compare cross-board quality deltas"]


__all__ = ["CrossBoardImprovementService"]
