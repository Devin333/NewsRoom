from __future__ import annotations

from datetime import datetime, timezone as _tz
UTC = _tz.utc

from backend.projects.dto import RankedProject
from backend.projects.models import (
    Project,
    ProjectDataset,
    ProjectGrowthSnapshot,
    ProjectMetricSnapshot,
    UserProjectInteractionEvent,
    WatchlistItem,
)


def rank_hot_projects(
    dataset: ProjectDataset,
    *,
    interactions: list[UserProjectInteractionEvent] | None = None,
    watchlist_items: list[WatchlistItem] | None = None,
    limit: int | None = None,
) -> list[RankedProject]:
    interactions = interactions or []
    watchlist_items = watchlist_items or []
    ranked = [
        _ranked_hot(project, dataset, interactions=interactions, watchlist_items=watchlist_items)
        for project in dataset.projects
    ]
    ranked.sort(key=lambda item: (item.score, item.project.updated_at), reverse=True)
    return _with_rank(ranked[:limit] if limit else ranked)


def rank_rising_projects(
    dataset: ProjectDataset,
    *,
    interactions: list[UserProjectInteractionEvent] | None = None,
    watchlist_items: list[WatchlistItem] | None = None,
    limit: int | None = None,
) -> list[RankedProject]:
    interactions = interactions or []
    watchlist_items = watchlist_items or []
    ranked = [
        _ranked_rising(project, dataset, interactions=interactions, watchlist_items=watchlist_items)
        for project in dataset.projects
    ]
    ranked.sort(key=lambda item: (item.score, item.project.updated_at), reverse=True)
    return _with_rank(ranked[:limit] if limit else ranked)


def hot_score(
    project: Project,
    dataset: ProjectDataset,
    *,
    interactions: list[UserProjectInteractionEvent] | None = None,
    watchlist_items: list[WatchlistItem] | None = None,
) -> tuple[float, dict[str, float], str]:
    metric = _latest_metric(dataset, project.id)
    growth = _latest_growth(dataset, project.id)
    interactions = interactions or []
    watchlist_items = watchlist_items or []
    factors = {
        "external_heat": _external_heat(metric, growth),
        "internal_behavior": _internal_behavior(project.id, metric, interactions, watchlist_items),
        "technical_relevance": _technical_relevance(project, metric),
        "freshness": _freshness(project, metric),
        "source_trust": _source_trust(project, metric, dataset),
    }
    score = _weighted(
        factors,
        {
            "external_heat": 0.32,
            "internal_behavior": 0.20,
            "technical_relevance": 0.18,
            "freshness": 0.14,
            "source_trust": 0.16,
        },
    )
    reason = (
        "Hot score combines external heat, internal behavior, technical relevance, "
        f"freshness, and source trust; strongest factor={_strongest_factor(factors)}."
    )
    return score, factors, reason


def rising_score(
    project: Project,
    dataset: ProjectDataset,
    *,
    interactions: list[UserProjectInteractionEvent] | None = None,
    watchlist_items: list[WatchlistItem] | None = None,
) -> tuple[float, dict[str, float], str]:
    metric = _latest_metric(dataset, project.id)
    growth = _latest_growth(dataset, project.id)
    interactions = interactions or []
    watchlist_items = watchlist_items or []
    factors = {
        "growth_speed": _growth_speed(growth),
        "novelty": _novelty(project),
        "update_frequency": _update_frequency(metric, growth),
        "early_quality": _early_quality(metric, project),
        "attention_growth": _attention_growth(project.id, growth, interactions, watchlist_items),
    }
    score = _weighted(
        factors,
        {
            "growth_speed": 0.32,
            "novelty": 0.18,
            "update_frequency": 0.16,
            "early_quality": 0.18,
            "attention_growth": 0.16,
        },
    )
    reason = (
        "Rising score emphasizes velocity, novelty, update frequency, early quality, "
        f"and attention growth; strongest factor={_strongest_factor(factors)}."
    )
    return score, factors, reason


def _ranked_hot(
    project: Project,
    dataset: ProjectDataset,
    *,
    interactions: list[UserProjectInteractionEvent],
    watchlist_items: list[WatchlistItem],
) -> RankedProject:
    score, factors, reason = hot_score(project, dataset, interactions=interactions, watchlist_items=watchlist_items)
    return RankedProject(project=project, rank=0, score=score, reason=reason, factors=factors)


def _ranked_rising(
    project: Project,
    dataset: ProjectDataset,
    *,
    interactions: list[UserProjectInteractionEvent],
    watchlist_items: list[WatchlistItem],
) -> RankedProject:
    score, factors, reason = rising_score(project, dataset, interactions=interactions, watchlist_items=watchlist_items)
    return RankedProject(project=project, rank=0, score=score, reason=reason, factors=factors)


def _with_rank(items: list[RankedProject]) -> list[RankedProject]:
    return [item.model_copy(update={"rank": index + 1}) for index, item in enumerate(items)]


def _latest_metric(dataset: ProjectDataset, project_id: str) -> ProjectMetricSnapshot | None:
    values = [item for item in dataset.metric_snapshots if item.project_id == project_id]
    return max(values, key=lambda item: item.snapshot_at) if values else None


def _latest_growth(dataset: ProjectDataset, project_id: str) -> ProjectGrowthSnapshot | None:
    values = [item for item in dataset.growth_snapshots if item.project_id == project_id]
    return max(values, key=lambda item: item.computed_at) if values else None


def _external_heat(metric: ProjectMetricSnapshot | None, growth: ProjectGrowthSnapshot | None) -> float:
    if metric is None:
        return 0.0
    score = 0.0
    score += _log_norm(metric.github_stars, 5000) * 0.28
    score += _log_norm(metric.github_forks, 1000) * 0.12
    score += _log_norm(metric.product_hunt_votes, 1000) * 0.16
    score += _log_norm(metric.hn_points, 500) * 0.16
    score += _log_norm(metric.reddit_score, 500) * 0.10
    score += _growth_speed(growth) * 0.18
    return _bounded(score)


def _internal_behavior(
    project_id: str,
    metric: ProjectMetricSnapshot | None,
    interactions: list[UserProjectInteractionEvent],
    watchlist_items: list[WatchlistItem],
) -> float:
    metric_score = 0.0
    if metric is not None:
        metric_score = min(
            1.0,
            metric.internal_views * 0.01
            + metric.internal_saves * 0.06
            + metric.internal_watches * 0.10
            + metric.internal_lab_uses * 0.12,
        )
    interaction_score = min(
        1.0,
        sum(event.signal_strength for event in interactions if event.target_id == project_id and event.target_type in {"project", "tool"}) / 12,
    )
    watch_score = min(1.0, sum(1 for item in watchlist_items if item.project_id == project_id and item.status == "active") / 5)
    return _bounded(metric_score * 0.45 + interaction_score * 0.35 + watch_score * 0.20)


def _technical_relevance(project: Project, metric: ProjectMetricSnapshot | None) -> float:
    feature_score = 0.0
    if metric and metric.metadata:
        feature_score = max(
            float(metric.metadata.get("technology_mapping") or 0),
            float(metric.metadata.get("repo_health") or 0),
            float(metric.metadata.get("community_adoption") or 0),
        )
    tag_score = min(1.0, len(project.tags) / 6)
    return _bounded(max(feature_score, tag_score * 0.7, project.source_confidence * 0.5))


def _freshness(project: Project, metric: ProjectMetricSnapshot | None) -> float:
    reference = metric.snapshot_at if metric is not None else project.updated_at
    age_days = max(0.0, (_now() - reference).total_seconds() / 86400)
    if age_days <= 7:
        return 1.0
    if age_days <= 30:
        return 0.75
    if age_days <= 90:
        return 0.45
    return 0.2


def _source_trust(project: Project, metric: ProjectMetricSnapshot | None, dataset: ProjectDataset) -> float:
    source_count = sum(1 for source in dataset.sources if source.project_id == project.id)
    quality = metric.quality_score if metric is not None and metric.quality_score is not None else project.source_confidence
    return _bounded(quality * 0.65 + min(1.0, source_count / 3) * 0.35)


def _growth_speed(growth: ProjectGrowthSnapshot | None) -> float:
    if growth is None:
        return 0.0
    return _bounded(
        _log_norm(growth.stars_delta, 500)
        + _log_norm(growth.votes_delta, 500) * 0.6
        + _log_norm(growth.mentions_delta, 30) * 0.4
    )


def _novelty(project: Project) -> float:
    age_days = max(0.0, (_now() - project.created_at).total_seconds() / 86400)
    if age_days <= 14:
        return 1.0
    if age_days <= 45:
        return 0.75
    if age_days <= 120:
        return 0.45
    return 0.20


def _update_frequency(metric: ProjectMetricSnapshot | None, growth: ProjectGrowthSnapshot | None) -> float:
    releases = growth.release_count if growth is not None else 0
    activity = metric.activity_score if metric is not None and metric.activity_score is not None else 0.0
    return _bounded(activity * 0.70 + min(1.0, releases / 4) * 0.30)


def _early_quality(metric: ProjectMetricSnapshot | None, project: Project) -> float:
    quality = metric.quality_score if metric is not None and metric.quality_score is not None else None
    evidence = metric.evidence_score if metric is not None and metric.evidence_score is not None else 0.0
    return _bounded((quality if quality is not None else project.source_confidence) * 0.65 + evidence * 0.35)


def _attention_growth(
    project_id: str,
    growth: ProjectGrowthSnapshot | None,
    interactions: list[UserProjectInteractionEvent],
    watchlist_items: list[WatchlistItem],
) -> float:
    growth_score = min(1.0, (growth.internal_watch_delta if growth is not None else 0) / 10)
    interaction_score = min(
        1.0,
        sum(event.signal_strength for event in interactions if event.target_id == project_id) / 10,
    )
    watch_score = min(1.0, sum(1 for item in watchlist_items if item.project_id == project_id) / 6)
    return _bounded(growth_score * 0.35 + interaction_score * 0.40 + watch_score * 0.25)


def _weighted(factors: dict[str, float], weights: dict[str, float]) -> float:
    total_weight = sum(weights.values()) or 1.0
    return round(sum(_bounded(factors.get(name, 0.0)) * weight for name, weight in weights.items()) / total_weight, 4)


def _strongest_factor(factors: dict[str, float]) -> str:
    if not factors:
        return "none"
    return max(factors.items(), key=lambda item: item[1])[0]


def _log_norm(value: int | float | None, scale: int | float) -> float:
    if value is None or value <= 0:
        return 0.0
    return _bounded(float(value) / (float(value) + float(scale)))


def _bounded(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def _now() -> datetime:
    return datetime.now(UTC)
