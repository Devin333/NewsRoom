from __future__ import annotations

from business.boards.cross_board.workflows.daily_intelligence.quality_observability import (
    aggregate_quality_gate_observability_metrics,
    quality_gate_observability_metrics,
)


def test_quality_gate_observability_metrics_projects_single_run_rates() -> None:
    metrics = quality_gate_observability_metrics(
        blocked=True,
        rewrite_required=False,
        human_review_required=True,
        memory_quality_result={
            "issues": [
                {"issue_type": "claim_conflict"},
                {"issue_type": "unsupported_claim"},
            ]
        },
    )

    assert metrics == {
        "sample_count": 1,
        "block_count": 1,
        "rewrite_count": 0,
        "human_review_count": 1,
        "memory_conflict_count": 1,
        "memory_conflict_run_count": 1,
        "block_rate": 1.0,
        "rewrite_rate": 0.0,
        "human_review_rate": 1.0,
        "memory_conflict_rate": 1.0,
    }


def test_quality_gate_observability_metrics_prefers_memory_metadata_conflict_count() -> None:
    metrics = quality_gate_observability_metrics(
        blocked=False,
        rewrite_required=True,
        human_review_required=False,
        memory_quality_result={
            "issues": [{"issue_type": "claim_conflict"}],
            "metadata": {"conflict_count": 3},
        },
    )

    assert metrics["block_rate"] == 0.0
    assert metrics["rewrite_rate"] == 1.0
    assert metrics["memory_conflict_count"] == 3
    assert metrics["memory_conflict_run_count"] == 1
    assert metrics["memory_conflict_rate"] == 1.0


def test_aggregate_quality_gate_observability_metrics_sums_cross_run_counts() -> None:
    aggregate = aggregate_quality_gate_observability_metrics(
        [
            {
                "sample_count": 1,
                "block_count": 1,
                "rewrite_count": 0,
                "human_review_count": 1,
                "memory_conflict_count": 2,
                "memory_conflict_run_count": 1,
            },
            {
                "sample_count": 2,
                "block_count": 1,
                "rewrite_count": 2,
                "human_review_count": 0,
                "memory_conflict_count": 0,
                "memory_conflict_run_count": 0,
            },
        ]
    )

    assert aggregate == {
        "sample_count": 3,
        "block_count": 2,
        "rewrite_count": 2,
        "human_review_count": 1,
        "memory_conflict_count": 2,
        "memory_conflict_run_count": 1,
        "block_rate": 2 / 3,
        "rewrite_rate": 2 / 3,
        "human_review_rate": 1 / 3,
        "memory_conflict_rate": 1 / 3,
    }


def test_aggregate_quality_gate_observability_metrics_projects_legacy_flags() -> None:
    aggregate = aggregate_quality_gate_observability_metrics(
        [
            {"blocked": True, "rewrite_required": False, "human_review_required": True},
            {"blocked": False, "rewrite_required": True, "human_review_required": False},
        ]
    )

    assert aggregate["sample_count"] == 2
    assert aggregate["block_count"] == 1
    assert aggregate["rewrite_count"] == 1
    assert aggregate["human_review_count"] == 1
    assert aggregate["block_rate"] == 0.5
    assert aggregate["rewrite_rate"] == 0.5
    assert aggregate["human_review_rate"] == 0.5


def test_aggregate_quality_gate_observability_metrics_accepts_to_dict_models() -> None:
    aggregate = aggregate_quality_gate_observability_metrics(
        [
            _MetricModel(
                {
                    "sample_count": 1,
                    "block_count": 0,
                    "rewrite_count": 0,
                    "human_review_count": 0,
                    "memory_conflict_count": 4,
                    "memory_conflict_run_count": 1,
                }
            )
        ]
    )

    assert aggregate["sample_count"] == 1
    assert aggregate["memory_conflict_count"] == 4
    assert aggregate["memory_conflict_run_count"] == 1
    assert aggregate["memory_conflict_rate"] == 1.0


def test_aggregate_quality_gate_observability_metrics_ignores_empty_inputs() -> None:
    assert aggregate_quality_gate_observability_metrics(None) == {
        "sample_count": 0,
        "block_count": 0,
        "rewrite_count": 0,
        "human_review_count": 0,
        "memory_conflict_count": 0,
        "memory_conflict_run_count": 0,
        "block_rate": 0.0,
        "rewrite_rate": 0.0,
        "human_review_rate": 0.0,
        "memory_conflict_rate": 0.0,
    }
    assert aggregate_quality_gate_observability_metrics(["invalid"])["sample_count"] == 0


class _MetricModel:
    def __init__(self, payload: dict) -> None:
        self._payload = payload

    def to_dict(self) -> dict:
        return dict(self._payload)
