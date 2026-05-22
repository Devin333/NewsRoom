from __future__ import annotations

from collections import Counter
from typing import Any


class TrendSynthesizer:
    def synthesize(self, board_payloads: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
        trends = []
        for board_type, payload in board_payloads.items():
            terms = _terms(payload)
            if not terms:
                continue
            trends.append(
                {
                    "trend_type": _trend_type(board_type),
                    "board_type": board_type,
                    "title": f"{board_type} trend: {terms[0]}",
                    "entities": terms[:5],
                    "strength": round(min(1.0, 0.45 + len(terms) * 0.08), 4),
                    "reason": "Derived from board cards, subscription targets, and trend metadata.",
                }
            )
        cross_terms = _shared_terms(board_payloads)
        if cross_terms:
            trends.append(
                {
                    "trend_type": "cross_cutting",
                    "board_type": "cross_board",
                    "title": f"Cross-cutting trend: {cross_terms[0]}",
                    "entities": cross_terms[:8],
                    "strength": round(min(1.0, 0.55 + len(cross_terms) * 0.06), 4),
                    "reason": "Entity appears across multiple board outputs.",
                }
            )
        return trends


def _trend_type(board_type: str) -> str:
    return {
        "ai_news": "product",
        "paper_radar": "research",
        "project_radar": "project",
        "community_pulse": "community",
    }.get(board_type, "cross_cutting")


def _terms(payload: dict[str, Any]) -> list[str]:
    found: list[str] = []
    for card in payload.get("cards") or []:
        if isinstance(card, dict):
            found.extend(_entity_names(card))
            title = str(card.get("title") or "").strip()
            if title:
                found.append(title.split()[0])
    subscription = payload.get("subscription_payload") or {}
    for target in subscription.get("targets") or []:
        if isinstance(target, dict):
            found.extend(str(entity) for entity in target.get("entities") or [])
    return _stable_unique(found)


def _shared_terms(board_payloads: dict[str, dict[str, Any]]) -> list[str]:
    counts = Counter()
    for payload in board_payloads.values():
        counts.update(set(_terms(payload)))
    return [term for term, count in counts.most_common() if count >= 2]


def _entity_names(card: dict[str, Any]) -> list[str]:
    names: list[str] = []
    for key in ("entities", "related_entities"):
        for entity in card.get(key) or []:
            if isinstance(entity, dict):
                value = entity.get("name") or entity.get("normalized_name")
            else:
                value = entity
            if value:
                names.append(str(value))
    return names


def _stable_unique(values: list[str]) -> list[str]:
    seen = set()
    result = []
    for value in values:
        text = str(value).strip()
        if not text or text.casefold() in seen:
            continue
        seen.add(text.casefold())
        result.append(text)
    return result


__all__ = ["TrendSynthesizer"]
