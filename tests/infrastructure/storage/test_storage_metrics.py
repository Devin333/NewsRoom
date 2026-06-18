import json
from datetime import UTC, datetime
from hashlib import sha256

from infrastructure.storage.artifacts import ArtifactRef, LocalJsonArtifactIndexStore
from infrastructure.storage.events import EventRecord, LocalJsonEventStore
from infrastructure.storage.lineage import LineageRef, LocalJsonLineageStore
from infrastructure.storage.metrics import LocalStorageMetricsCollector, StorageMetrics


def test_storage_metrics_to_dict() -> None:
    metrics = StorageMetrics(
        runs_count=1,
        reports_count=1,
        artifacts_count=2,
        source_items_count=5,
        evidence_items_count=6,
        claims_count=7,
        quality_results_count=8,
        vector_documents_count=9,
        artifact_bytes_total=42,
        events_count=3,
        lineage_refs_count=4,
        postgres_query_latency_ms=12.5,
        vector_search_latency_ms=22.5,
        cache_hit_rate=0.75,
        generated_at=datetime(2026, 5, 11, 1, 0, tzinfo=UTC),
        metadata={"source": "test"},
    )

    assert metrics.to_dict() == {
        "runs_count": 1,
        "reports_count": 1,
        "artifacts_count": 2,
        "source_items_count": 5,
        "evidence_items_count": 6,
        "claims_count": 7,
        "quality_results_count": 8,
        "vector_documents_count": 9,
        "artifact_bytes_total": 42,
        "events_count": 3,
        "lineage_refs_count": 4,
        "postgres_query_latency_ms": 12.5,
        "vector_search_latency_ms": 22.5,
        "cache_hit_rate": 0.75,
        "generated_at": "2026-05-11T01:00:00Z",
        "metadata": {"source": "test"},
    }


def test_local_storage_metrics_collector_counts_local_records(tmp_path) -> None:
    _write_manifest(
        tmp_path,
        run_id="metrics-run",
        artifacts={
            "report_json": "report.json",
            "manifest": "manifest.json",
        },
    )
    LocalJsonArtifactIndexStore(tmp_path / "_records" / "artifact_index").index_artifact(
        ArtifactRef(
            artifact_id="report_json",
            run_id="metrics-run",
            artifact_type="report_json",
            path="report.json",
            content_type="application/json",
            size_bytes=42,
            checksum=sha256(b"{}").hexdigest(),
            redacted=True,
            created_at=datetime(2026, 5, 11, 1, 0, tzinfo=UTC),
        )
    )
    LocalJsonEventStore(tmp_path / "_records" / "events").append_event(
        EventRecord(
            event_id="event-1",
            run_id="metrics-run",
            workflow_id="daily",
            step_id="draft_report",
            event_type="workflow_step_completed",
            timestamp=datetime(2026, 5, 11, 1, 0, tzinfo=UTC),
        )
    )
    LocalJsonLineageStore(tmp_path / "_records" / "lineage").record(
        LineageRef(
            run_id="metrics-run",
            source_type="source_item",
            source_id="raw-1",
            target_type="report",
            target_id="metrics-run:final",
            relation_type="source_to_report",
            created_at=datetime(2026, 5, 11, 1, 0, tzinfo=UTC),
        )
    )

    metrics = LocalStorageMetricsCollector(tmp_path).collect()

    assert metrics.runs_count == 1
    assert metrics.reports_count == 1
    assert metrics.artifacts_count == 1
    assert metrics.artifact_bytes_total == 42
    assert metrics.events_count == 1
    assert metrics.lineage_refs_count == 1
    assert metrics.metadata["source"] == "local_json"


def test_local_storage_metrics_collector_counts_blocked_report_artifact(tmp_path) -> None:
    _write_manifest(
        tmp_path,
        run_id="run-blocked",
        artifacts={
            "blocked_report": "blocked_report.json",
            "manifest": "manifest.json",
        },
    )

    metrics = LocalStorageMetricsCollector(tmp_path).collect()

    assert metrics.runs_count == 1
    assert metrics.reports_count == 1


def _write_manifest(tmp_path, *, run_id: str, artifacts: dict[str, str]) -> None:
    run_dir = tmp_path / run_id
    run_dir.mkdir()
    (run_dir / "manifest.json").write_text(
        json.dumps(
            {
                "run_id": run_id,
                "status": "succeeded",
                "artifacts": artifacts,
            }
        ),
        encoding="utf-8",
    )
