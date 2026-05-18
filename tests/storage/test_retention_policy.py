from datetime import UTC, datetime

import pytest

from storage.artifacts import ArtifactRef, ArtifactWriteRequest, FilesystemArtifactStore
from storage.lifecycle import ArtifactRetentionPlanner, LocalArtifactRetentionExecutor, RetentionPolicy


def _ref(artifact_id: str, artifact_type: str, created_at: datetime) -> ArtifactRef:
    return ArtifactRef(
        artifact_id=artifact_id,
        run_id="run-1",
        artifact_type=artifact_type,
        path=f"artifacts/{artifact_id}.json",
        content_type="application/json",
        created_at=created_at,
    )


def test_retention_policy_round_trips() -> None:
    policy = RetentionPolicy(
        raw_source_retention_days=7,
        llm_artifact_retention_days=14,
        run_artifact_retention_days=30,
        report_retention_days=None,
        evidence_retention_days=365,
        vector_retention_days=90,
    )

    restored = RetentionPolicy.from_dict(policy.to_dict())

    assert restored == policy
    assert restored.retention_days_for("source_item") == 7
    assert restored.retention_days_for("llm_response") == 14
    assert restored.retention_days_for("output") == 30
    assert restored.retention_days_for("report_json") is None
    assert restored.retention_days_for("evidence_bundle") == 365
    assert restored.retention_days_for("vector_memory") == 90


def test_retention_policy_uses_run_default_for_quality_and_events() -> None:
    policy = RetentionPolicy(
        raw_source_retention_days=7,
        llm_artifact_retention_days=14,
        run_artifact_retention_days=30,
        report_retention_days=None,
        evidence_retention_days=365,
        vector_retention_days=90,
    )

    assert policy.retention_days_for("quality_result") == 30
    assert policy.retention_days_for("quality_gate_metrics") == 30
    assert policy.retention_days_for("events") == 30


    with pytest.raises(ValueError, match="raw_source_retention_days"):
        RetentionPolicy(raw_source_retention_days=-1)


def test_artifact_retention_planner_marks_expired_and_kept_artifacts() -> None:
    now = datetime(2026, 5, 11, tzinfo=UTC)
    old = datetime(2026, 4, 1, tzinfo=UTC)
    recent = datetime(2026, 5, 1, tzinfo=UTC)
    refs = [
        _ref("raw-old", "source_item", old),
        _ref("raw-recent", "source_item", recent),
        _ref("report-old", "report_json", old),
        _ref("output-old", "output", datetime(2025, 1, 1, tzinfo=UTC)),
    ]

    plan = ArtifactRetentionPlanner(RetentionPolicy()).plan(refs, now=now)

    decisions = {decision.artifact_ref.artifact_id: decision for decision in plan.decisions}
    assert decisions["raw-old"].action == "delete"
    assert decisions["raw-old"].reason == "retention_expired"
    assert decisions["raw-recent"].action == "keep"
    assert decisions["raw-recent"].reason == "retention_active"
    assert decisions["report-old"].action == "keep"
    assert decisions["report-old"].reason == "retention_indefinite"
    assert decisions["output-old"].action == "delete"
    assert plan.to_dict()["delete_count"] == 2


def test_local_artifact_retention_executor_deletes_only_expired_files(tmp_path) -> None:
    store = FilesystemArtifactStore(tmp_path)
    old_raw = store.write(
        ArtifactWriteRequest(
            run_id="run-1",
            artifact_id="raw-old",
            artifact_type="source_item",
            content=b"raw",
            content_type="text/plain",
            created_at=datetime(2026, 4, 1, tzinfo=UTC),
        )
    )
    old_report = store.write(
        ArtifactWriteRequest(
            run_id="run-1",
            artifact_id="report-old",
            artifact_type="report_json",
            content=b"{}",
            content_type="application/json",
            created_at=datetime(2026, 4, 1, tzinfo=UTC),
        )
    )
    plan = ArtifactRetentionPlanner().plan(
        [old_raw, old_report],
        now=datetime(2026, 5, 11, tzinfo=UTC),
    )

    deleted = LocalArtifactRetentionExecutor(tmp_path).delete_expired(plan)

    assert deleted == [old_raw]
    assert store.exists(old_raw) is False
    assert store.exists(old_report) is True


def test_local_artifact_retention_executor_can_dry_run_expired_files(tmp_path) -> None:
    store = FilesystemArtifactStore(tmp_path)
    old_raw = store.write(
        ArtifactWriteRequest(
            run_id="run-1",
            artifact_id="raw-old",
            artifact_type="source_item",
            content=b"raw",
            content_type="text/plain",
            created_at=datetime(2026, 4, 1, tzinfo=UTC),
        )
    )
    plan = ArtifactRetentionPlanner().plan(
        [old_raw],
        now=datetime(2026, 5, 11, tzinfo=UTC),
    )

    selected = LocalArtifactRetentionExecutor(tmp_path).delete_expired(plan, dry_run=True)

    assert selected == [old_raw]
    assert store.exists(old_raw) is True


def test_retention_policy_keeps_manifest_request_indefinitely() -> None:
    policy = RetentionPolicy()

    assert policy.retention_days_for("manifest") is None
    assert policy.retention_days_for("request") is None
    assert policy.retention_days_for("workflow_spec") is None
