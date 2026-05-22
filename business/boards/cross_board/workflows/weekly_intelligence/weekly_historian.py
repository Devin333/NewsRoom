from __future__ import annotations

from typing import Any


class WeeklyHistorian:
    def build(self, source_reports: list[dict[str, Any]], weekly_trends: dict[str, Any]) -> dict[str, Any]:
        timeline = [
            {
                "finished_at": report.get("finished_at"),
                "report_id": report.get("report_id"),
                "title": report.get("title"),
                "quality_score": report.get("quality_score"),
            }
            for report in sorted(source_reports, key=lambda item: str(item.get("finished_at") or ""))
        ]
        recurring = [item.get("entity") for item in weekly_trends.get("recurring_entities") or [] if item.get("entity")]
        emerging = [item.get("topic") for item in weekly_trends.get("emerging_topics") or [] if item.get("topic")]
        return {
            "timeline": timeline,
            "repeated_themes": recurring,
            "new_vs_recurring": {
                "new_topics": [topic for topic in emerging if topic not in recurring],
                "recurring_entities": recurring,
            },
            "significance_delta": _significance_delta(timeline),
        }


def _significance_delta(timeline: list[dict[str, Any]]) -> float | None:
    values = [float(item["quality_score"]) for item in timeline if item.get("quality_score") is not None]
    if len(values) < 2:
        return None
    return round(values[-1] - values[0], 4)


__all__ = ["WeeklyHistorian"]
