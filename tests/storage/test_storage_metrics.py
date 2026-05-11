from datetime import UTC, datetime

from storage.metrics import LocalStorageMetricsCollector, StorageMetrics
from workflows.daily_intelligence import DailyIntelligenceRunner


def test_storage_metrics_to_dict() -> None:
    metrics = StorageMetrics(
        runs_count=1,
        reports_count=1,
        artifacts_count=2,
        artifact_bytes_total=42,
        events_count=3,
        lineage_refs_count=4,
        generated_at=datetime(2026, 5, 11, 1, 0, tzinfo=UTC),
        metadata={"source": "test"},
    )

    assert metrics.to_dict() == {
        "runs_count": 1,
        "reports_count": 1,
        "artifacts_count": 2,
        "artifact_bytes_total": 42,
        "events_count": 3,
        "lineage_refs_count": 4,
        "generated_at": "2026-05-11T01:00:00Z",
        "metadata": {"source": "test"},
    }


def test_local_storage_metrics_collector_counts_real_workflow_records(tmp_path) -> None:
    result = DailyIntelligenceRunner(artifact_root=tmp_path).run(
        profile="live-offline",
        topic="AI policy",
        source_limit=1,
        run_id="metrics-run",
    )

    metrics = LocalStorageMetricsCollector(tmp_path).collect()

    assert result.status.value == "succeeded"
    assert metrics.runs_count == 1
    assert metrics.reports_count == 1
    assert metrics.artifacts_count >= 1
    assert metrics.artifact_bytes_total > 0
    assert metrics.events_count > 0
    assert metrics.lineage_refs_count > 0
    assert metrics.metadata["source"] == "local_json"
