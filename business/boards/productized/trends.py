from __future__ import annotations

from typing import Any

from business.foundation import Signal


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


def _title_for_group(group: dict[str, Any], signals: list[Signal]) -> str:
    ids = {str(item) for item in group.get("item_ids") or []}
    for signal in signals:
        if signal.signal_id in ids or (signal.source.external_id and signal.source.external_id in ids):
            return signal.title
    return str(group.get("event_id") or "Event")


__all__ = ["ProductizedTrendEventService"]
