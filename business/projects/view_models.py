from __future__ import annotations

from typing import Any

from business.projects.dto import ProjectCardView, ProjectMetricView, RankedProject
from business.projects.models import Project, ProjectDataset


def project_card_view(
    project: Project,
    dataset: ProjectDataset,
    *,
    rank: int | None = None,
    hot_score: float | None = None,
    rising_score: float | None = None,
    rank_reason: str | None = None,
) -> ProjectCardView:
    metric = _latest_metric(dataset, project.id)
    growth = _latest_growth(dataset, project.id)
    return ProjectCardView(
        id=project.id,
        slug=project.slug,
        name=project.name,
        tagline=project.tagline,
        description=project.description,
        canonical_url=project.canonical_url,
        website_url=project.website_url,
        github_url=project.github_url,
        docs_url=project.docs_url,
        demo_url=project.demo_url,
        project_type=project.project_type.value,
        category=project.category,
        tags=list(project.tags),
        source_confidence=project.source_confidence,
        hot_score=hot_score,
        rising_score=rising_score,
        rank=rank,
        rank_reason=rank_reason,
        metric_summary=_metric_summary(metric, growth),
        capability_count=sum(1 for item in dataset.capabilities if item.project_id == project.id),
        case_count=sum(1 for item in dataset.cases if item.project_id == project.id),
        source_count=sum(1 for item in dataset.sources if item.project_id == project.id),
        updated_at=project.updated_at.isoformat(),
    )


def ranked_project_card_view(item: RankedProject, dataset: ProjectDataset, *, score_type: str) -> ProjectCardView:
    return project_card_view(
        item.project,
        dataset,
        rank=item.rank,
        hot_score=item.score if score_type == "hot" else None,
        rising_score=item.score if score_type == "rising" else None,
        rank_reason=item.reason,
    )


def dataset_metrics(dataset: ProjectDataset) -> list[ProjectMetricView]:
    return [
        ProjectMetricView(label="Projects", value=len(dataset.projects), hint="Real Project Radar derived project count"),
        ProjectMetricView(label="Tools", value=len(dataset.tool_profiles), hint="Derived tool profiles"),
        ProjectMetricView(label="Cases", value=len(dataset.cases), hint="Derived module cases"),
        ProjectMetricView(label="Collections", value=len(dataset.collections), hint="Real-data collections"),
    ]


def _latest_metric(dataset: ProjectDataset, project_id: str):
    values = [item for item in dataset.metric_snapshots if item.project_id == project_id]
    return max(values, key=lambda item: item.snapshot_at) if values else None


def _latest_growth(dataset: ProjectDataset, project_id: str):
    values = [item for item in dataset.growth_snapshots if item.project_id == project_id]
    return max(values, key=lambda item: item.computed_at) if values else None


def _metric_summary(metric: Any, growth: Any) -> dict[str, Any]:
    if metric is None and growth is None:
        return {}
    return {
        "github_stars": getattr(metric, "github_stars", None),
        "github_forks": getattr(metric, "github_forks", None),
        "source_mentions": getattr(metric, "source_mentions", None),
        "quality_score": getattr(metric, "quality_score", None),
        "activity_score": getattr(metric, "activity_score", None),
        "evidence_score": getattr(metric, "evidence_score", None),
        "stars_delta_7d": getattr(growth, "stars_delta", None),
        "mentions_delta_7d": getattr(growth, "mentions_delta", None),
    }
