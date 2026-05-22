from __future__ import annotations

from collections import Counter
from typing import Any

from business.boards.cross_board.conflict_detector import ConflictDetector
from business.boards.cross_board.cross_board_improvement import CrossBoardImprovementService
from business.boards.cross_board.cross_board_subscription import CrossBoardSubscriptionBuilder
from business.boards.cross_board.trend_synthesizer import TrendSynthesizer


class CrossBoardIntelligenceService:
    def build(
        self,
        board_payloads: dict[str, dict[str, Any]],
        *,
        topic: str | None = None,
        include_improvement: bool = True,
    ) -> dict[str, Any]:
        normalized = {board_type: dict(payload) for board_type, payload in board_payloads.items()}
        shared_entities = _shared_entities(normalized)
        shared_trends = TrendSynthesizer().synthesize(normalized)
        conflicts = ConflictDetector().detect(normalized)
        subscription_payload = CrossBoardSubscriptionBuilder().build(normalized, topic=topic)
        improvement_report = (
            CrossBoardImprovementService().aggregate(normalized)
            if include_improvement
            else {"recommendations": [], "reports": [], "priority_order": [], "next_actions": []}
        )
        return {
            "cross_board_summary": _summary(normalized, shared_entities, shared_trends, conflicts),
            "shared_entities": shared_entities,
            "shared_trends": shared_trends,
            "conflicting_signals": conflicts,
            "board_coverage": _coverage(normalized),
            "recommendations": improvement_report.get("recommendations", []),
            "subscription_payload": subscription_payload,
            "improvement_report": improvement_report,
            "board_payloads": normalized,
        }


def _shared_entities(board_payloads: dict[str, dict[str, Any]]) -> list[str]:
    counts = Counter()
    for payload in board_payloads.values():
        entities = set()
        subscription = payload.get("subscription_payload") or {}
        for target in subscription.get("targets") or []:
            if isinstance(target, dict):
                entities.update(str(entity) for entity in target.get("entities") or [])
        counts.update(entity for entity in entities if entity)
    return [entity for entity, count in counts.most_common() if count >= 2]


def _coverage(board_payloads: dict[str, dict[str, Any]]) -> dict[str, Any]:
    coverage = {}
    for board_type, payload in board_payloads.items():
        cards = payload.get("cards") or []
        quality = payload.get("quality_summary") or {}
        coverage[board_type] = {
            "card_count": len(cards) if isinstance(cards, list) else 0,
            "quality_score": quality.get("score") if isinstance(quality, dict) else None,
            "subscription_ready": bool((payload.get("subscription_payload") or {}).get("delivery_hints", {}).get("subscription_ready")),
        }
    return coverage


def _summary(
    board_payloads: dict[str, dict[str, Any]],
    shared_entities: list[str],
    shared_trends: list[dict[str, Any]],
    conflicts: list[dict[str, Any]],
) -> str:
    return (
        f"Aggregated {len(board_payloads)} board(s), "
        f"{len(shared_entities)} shared entit(ies), "
        f"{len(shared_trends)} trend(s), and {len(conflicts)} conflict(s)."
    )


__all__ = ["CrossBoardIntelligenceService"]
