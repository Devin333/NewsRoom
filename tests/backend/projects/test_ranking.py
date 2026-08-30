from __future__ import annotations

from backend.projects.models import ProjectDataset
from backend.projects.ranking import rank_hot_projects, rank_rising_projects
from tests.backend.projects.helpers import project_dataset_payload


def test_hot_and_rising_rankings_explain_scores() -> None:
    dataset = ProjectDataset.model_validate(project_dataset_payload())

    hot = rank_hot_projects(dataset)
    rising = rank_rising_projects(dataset)

    assert hot[0].project.id == "project-langfuse"
    assert rising[0].project.id == "project-langfuse"
    assert hot[0].score > hot[-1].score
    assert rising[0].score > rising[-1].score
    assert hot[0].reason
    assert rising[0].reason
    assert "external_heat" in hot[0].factors
    assert "growth_speed" in rising[0].factors


def test_ranking_handles_missing_public_metrics_without_fabrication() -> None:
    dataset = ProjectDataset.model_validate(project_dataset_payload())
    private = next(project for project in dataset.projects if project.id == "project-missing-public-metrics")
    hot = next(item for item in rank_hot_projects(dataset) if item.project.id == private.id)
    rising = next(item for item in rank_rising_projects(dataset) if item.project.id == private.id)

    assert 0 <= hot.score <= 1
    assert 0 <= rising.score <= 1
    assert hot.factors["external_heat"] == 0
    assert rising.factors["growth_speed"] == 0
