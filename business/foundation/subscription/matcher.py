from __future__ import annotations

from typing import Any

from business.foundation.primitives import normalize_key


def board_subscription_defaults(board_type: str) -> tuple[list[str], list[str]]:
    mapping = {
        "ai_news": (
            ["ai_news", "product_update", "industry"],
            ["rss", "official_blog", "web"],
        ),
        "project_radar": (
            ["github", "project", "framework", "release"],
            ["github", "hackernews", "devto"],
        ),
        "paper_radar": (
            ["paper", "arxiv", "research", "benchmark"],
            ["arxiv", "paper"],
        ),
        "community_pulse": (
            ["community", "discussion", "sentiment", "developer"],
            ["reddit", "hackernews", "lobsters", "stackoverflow", "devto"],
        ),
        "cross_board": (
            ["cross_board", "daily", "intelligence"],
            ["rss", "official_blog", "github", "arxiv", "reddit", "hackernews"],
        ),
        "weekly_intelligence": (
            ["weekly", "trend", "intelligence"],
            ["daily_report", "board_output"],
        ),
    }
    return mapping.get(board_type, ([board_type], ["manual"]))


def extract_entities_from_cards(cards: list[Any]) -> list[str]:
    entities: list[str] = []
    for card in cards:
        payload = _payload(card)
        primary = payload.get("primary_object_ref")
        if isinstance(primary, dict):
            label = primary.get("label") or primary.get("object_id")
            if label:
                entities.append(str(label))
        for ref in payload.get("related_refs") or []:
            if isinstance(ref, dict):
                label = ref.get("label") or ref.get("object_id")
                if label:
                    entities.append(str(label))
        for key in ("entities", "related_entities"):
            for value in payload.get(key) or []:
                if isinstance(value, dict):
                    label = value.get("name") or value.get("label") or value.get("object_id") or value.get("normalized_name")
                else:
                    label = value
                if label:
                    entities.append(str(label))
        for value in payload.get("metadata", {}).get("entities", []) if isinstance(payload.get("metadata"), dict) else []:
            if value:
                entities.append(str(value))
    return _stable_unique(entities)


def subscription_match_score(tags: list[str], expected_tags: list[str]) -> float:
    normalized = {normalize_key(tag) for tag in tags}
    expected = {normalize_key(tag) for tag in expected_tags}
    if not expected:
        return 1.0
    return round(len(normalized & expected) / len(expected), 4)


def _payload(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    to_dict = getattr(value, "to_dict", None)
    if callable(to_dict):
        return to_dict()
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        return model_dump(mode="json")
    return {}


def _stable_unique(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        text = str(value).strip()
        marker = normalize_key(text)
        if not marker or marker in seen:
            continue
        seen.add(marker)
        result.append(text)
    return result


__all__ = ["board_subscription_defaults", "extract_entities_from_cards", "subscription_match_score"]
