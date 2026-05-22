from __future__ import annotations

from typing import Any

from business.foundation.subscription import DeliveryPlanBuilder, SubscriptionPayloadBuilder


class WeeklySubscriptionBuilder:
    def build(
        self,
        *,
        run_id: str,
        topic: str | None,
        source_reports: list[dict[str, Any]],
        weekly_trends: dict[str, Any],
        weekly_quality: dict[str, Any],
    ) -> dict[str, Any]:
        cards = [
            {
                "card_id": trend.get("trend_id"),
                "title": trend.get("topic"),
                "summary": f"Weekly trend from {trend.get('source_report_count', 0)} source report(s).",
                "entities": [item.get("entity") for item in weekly_trends.get("recurring_entities") or [] if item.get("entity")],
                "evidence_refs": [{"source_id": report.get("report_id"), "url": (report.get("source_urls") or [""])[0]} for report in source_reports],
            }
            for trend in weekly_trends.get("high_confidence_trends") or []
        ] or [
            {
                "card_id": "weekly-summary",
                "title": topic or "weekly intelligence",
                "summary": f"Weekly synthesis from {len(source_reports)} report(s).",
                "entities": [item.get("entity") for item in weekly_trends.get("recurring_entities") or [] if item.get("entity")],
                "evidence_refs": [{"source_id": report.get("report_id"), "url": (report.get("source_urls") or [""])[0]} for report in source_reports],
            }
        ]
        payload = SubscriptionPayloadBuilder().build(
            run_id=run_id,
            board_type="weekly_intelligence",
            topic=topic,
            cards=cards,
            summary=f"Weekly intelligence subscription payload for {topic or 'all topics'}.",
            quality_score=_optional_float(weekly_quality.get("score")),
            tags=["weekly", "intelligence", "trend"],
            source_types=["daily_report", "artifact"],
        )
        delivery_plan = DeliveryPlanBuilder().build(payload)
        return {**payload.to_dict(), "delivery_plan": delivery_plan.to_dict()}


def _optional_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


__all__ = ["WeeklySubscriptionBuilder"]
