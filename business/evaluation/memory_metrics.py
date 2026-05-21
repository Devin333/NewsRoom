from __future__ import annotations

from business.evaluation.models import clamp_metric


def memory_hit_rate(cards: list[object]) -> float:
    if not cards:
        return 0.0
    hits = 0
    for card in cards:
        metadata = getattr(card, "metadata", {}) or {}
        if isinstance(metadata, dict) and metadata.get("memory_features_used"):
            hits += 1
    return clamp_metric(hits / len(cards))


def memory_decision_impact(cards: list[object]) -> float:
    values: list[float] = []
    for card in cards:
        features = getattr(card, "ranking_features", {}) or {}
        if not isinstance(features, dict) or "memory_decision_score" not in features:
            continue
        values.append(abs(float(features["memory_decision_score"]) - 0.5) * 2.0)
    if not values:
        return 0.0
    return clamp_metric(sum(values) / len(values))


def memory_metrics(cards: list[object]) -> dict[str, float]:
    return {
        "memory_hit_rate": memory_hit_rate(cards),
        "memory_decision_impact": memory_decision_impact(cards),
    }
