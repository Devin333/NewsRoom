from __future__ import annotations

from typing import Any


class ConflictDetector:
    def detect(self, board_payloads: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
        conflicts: list[dict[str, Any]] = []
        quality_by_board = {
            board_type: _quality_score(payload.get("quality_summary"))
            for board_type, payload in board_payloads.items()
        }
        for left_board, left_score in quality_by_board.items():
            for right_board, right_score in quality_by_board.items():
                if left_board >= right_board:
                    continue
                shared = sorted(_entities(board_payloads[left_board]) & _entities(board_payloads[right_board]))
                if shared and left_score is not None and right_score is not None and abs(left_score - right_score) >= 0.35:
                    conflicts.append(
                        {
                            "conflict_type": "quality_judgment",
                            "entity": shared[0],
                            "boards": [left_board, right_board],
                            "scores": {left_board: left_score, right_board: right_score},
                            "reason": "Shared entity has materially different board quality scores.",
                        }
                    )
        conflicts.extend(_semantic_conflicts(board_payloads))
        return conflicts


def _semantic_conflicts(board_payloads: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    conflicts: list[dict[str, Any]] = []
    paper_entities = _entities(board_payloads.get("paper_radar") or {})
    community_entities = _entities(board_payloads.get("community_pulse") or {})
    if paper_entities & community_entities:
        conflicts.append(
            {
                "conflict_type": "paper_vs_community",
                "entity": sorted(paper_entities & community_entities)[0],
                "boards": ["paper_radar", "community_pulse"],
                "reason": "Research claim and community feedback should be reviewed together.",
            }
        )
    project_entities = _entities(board_payloads.get("project_radar") or {})
    news_entities = _entities(board_payloads.get("ai_news") or {})
    if project_entities & news_entities:
        conflicts.append(
            {
                "conflict_type": "project_release_vs_news_report",
                "entity": sorted(project_entities & news_entities)[0],
                "boards": ["project_radar", "ai_news"],
                "reason": "Project release and news coverage overlap.",
            }
        )
    return conflicts


def _quality_score(value: Any) -> float | None:
    if isinstance(value, dict):
        raw = value.get("score")
        try:
            return float(raw) if raw is not None else None
        except (TypeError, ValueError):
            return None
    return None


def _entities(payload: dict[str, Any]) -> set[str]:
    entities: set[str] = set()
    subscription = payload.get("subscription_payload") or {}
    for target in subscription.get("targets") or []:
        if isinstance(target, dict):
            entities.update(str(entity).casefold() for entity in target.get("entities") or [])
    for card in payload.get("cards") or []:
        if isinstance(card, dict):
            for entity in card.get("entities") or card.get("related_entities") or []:
                if isinstance(entity, dict):
                    name = entity.get("name") or entity.get("normalized_name")
                else:
                    name = entity
                if name:
                    entities.add(str(name).casefold())
    return {entity for entity in entities if entity}


__all__ = ["ConflictDetector"]
