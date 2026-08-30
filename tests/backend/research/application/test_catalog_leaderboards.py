from __future__ import annotations

from datetime import UTC, datetime

from backend.research.application.catalog import (
    InMemoryResearchCatalogRepository,
    ResearchPaperCatalogService,
)
from backend.research.application.catalog import CatalogLeaderboardResult
from backend.research.benchmark import ResearchScore


def _service() -> ResearchPaperCatalogService:
    repository = InMemoryResearchCatalogRepository()
    return ResearchPaperCatalogService(catalog_repository=repository)


def _score(
    score_id: str,
    value: float,
    *,
    direction: str = "higher_is_better",
    dataset_version: str = "v1",
    split: str = "test",
    protocol: str = "zero-shot",
    status: str = "verified",
) -> ResearchScore:
    return ResearchScore(
        score_id=score_id,
        paper_id=f"paper-{score_id}",
        benchmark_id="benchmark-1",
        dataset_id="dataset-1",
        metric_id="metric-1",
        value=value,
        source_refs=[f"source://{score_id}"],
        evidence_refs=[f"evidence://{score_id}"],
        verification_status=status,
        direction=direction,
        split=split,
        unit="%",
        evaluation_protocol=protocol,
        metadata={"dataset_version": dataset_version},
    )


def test_compare_scores_excludes_non_verified_and_sorts_higher_direction() -> None:
    result = _service().compare_scores(
        [
            _score("score-b", 90.0),
            _score("score-a", 90.0),
            _score("score-candidate", 99.0, status="candidate"),
        ]
    )

    assert [row["scoreId"] for row in result.rows] == ["score-a", "score-b"]
    assert result.groups[0]["rows"] == result.rows
    assert result.excluded_scores == [{"scoreId": "score-candidate", "reason": "status:candidate"}]


def test_compare_scores_sorts_lower_direction_and_separates_incompatible_groups() -> None:
    result = _service().compare_scores(
        [
            _score("low-b", 0.2, direction="lower_is_better"),
            _score("low-a", 0.1, direction="lower_is_better"),
            _score("other-version", 0.05, direction="lower_is_better", dataset_version="v2"),
        ]
    )

    assert len(result.groups) == 2
    assert result.rows == []
    first, second = result.groups
    assert first["compatibilityKey"]["datasetVersion"] == "v1"
    assert [row["scoreId"] for row in first["rows"]] == ["low-a", "low-b"]
    assert second["compatibilityKey"]["datasetVersion"] == "v2"
    assert [row["scoreId"] for row in second["rows"]] == ["other-version"]


def test_leaderboard_result_uses_independent_excluded_score_lists() -> None:
    left = CatalogLeaderboardResult(rows=[], observed_at=datetime.now(UTC))
    right = CatalogLeaderboardResult(rows=[], observed_at=datetime.now(UTC))

    left.excluded_scores.append({"scoreId": "left"})

    assert right.excluded_scores == []
