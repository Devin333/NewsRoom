from __future__ import annotations

from typing import Any

from business.boards.productized.models import ProductizedRunState
from business.foundation import Signal
from business.foundation.skills import BusinessSkillRuntime


class ProductizedTrendEventService:
    def build_events(self, deduplication_result: dict[str, Any], signals: list[Signal]) -> list[dict[str, Any]]:
        groups = deduplication_result.get("event_groups") if isinstance(deduplication_result, dict) else None
        if groups:
            return [
                {
                    "event_id": str(group.get("event_id")),
                    "title": _title_for_group(group, signals),
                    "summary": "Grouped board event.",
                    "item_ids": list(group.get("item_ids") or []),
                    "source_count": len(group.get("item_ids") or []),
                    "primary_source_count": 1,
                    "community_signal_count": sum(1 for signal in signals if signal.signal_type.value == "community_discussion"),
                    "evidence_status": "supported",
                    "impact_hints": ["engineering"],
                }
                for group in groups
                if isinstance(group, dict)
            ]
        return [
            {
                "event_id": signal.signal_id,
                "title": signal.title,
                "summary": signal.summary or signal.content or signal.title,
                "item_ids": [signal.signal_id],
                "source_count": 1,
                "primary_source_count": 1,
                "community_signal_count": 1 if signal.signal_type.value == "community_discussion" else 0,
                "evidence_status": "supported",
                "impact_hints": ["engineering"],
            }
            for signal in signals
        ]


class ProductizedTrendAnalysisService:
    def __init__(
        self,
        *,
        skill_runtime: BusinessSkillRuntime,
        event_service: ProductizedTrendEventService | None = None,
    ) -> None:
        self.skill_runtime = skill_runtime
        self.event_service = event_service or ProductizedTrendEventService()

    def analyze(
        self,
        *,
        request: dict[str, Any],
        ranked_signals: list[Signal],
        productized_run: ProductizedRunState,
    ) -> dict[str, Any]:
        skill_traces = list(productized_run.skill_traces)
        events = self.event_service.build_events(
            productized_run.deduplication_result,
            ranked_signals,
        )
        result = self.skill_runtime.run_trend_analysis(
            events,
            run_id=productized_run.run_id,
            fail_on_skill_error=bool(request.get("fail_on_skill_error", False)),
        )
        skill_traces.append(result.to_dict())
        run_state = productized_run.with_updates(
            trend_analysis=result.output,
            skill_traces=skill_traces,
        )
        return {"trend_analysis": result.output, "skill_traces": skill_traces, "productized_run": run_state}


def _title_for_group(group: dict[str, Any], signals: list[Signal]) -> str:
    ids = {str(item) for item in group.get("item_ids") or []}
    for signal in signals:
        if signal.signal_id in ids or (signal.source.external_id and signal.source.external_id in ids):
            return signal.title
    return str(group.get("event_id") or "Event")


__all__ = ["ProductizedTrendAnalysisService", "ProductizedTrendEventService"]
