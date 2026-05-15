from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

import pytest

from core.framework.artifacts import ArtifactManager
from core.framework.specs import StepSpec, WorkflowSpec, WorkflowStatus
from core.framework.workflow import (
    ArtifactPublishContext,
    ArtifactPublishPhase,
    ArtifactPublisherRegistry,
    DataBuffer,
    StepOutcome,
    RuntimeArtifactPublisher,
    WorkflowArtifactPublisherRegistry,
    register_manifest_artifact_once,
)
from storage.artifacts import ArtifactRef


def test_artifact_publish_context_normalizes_phase_and_status(tmp_path) -> None:
    context = _context(
        tmp_path,
        phase="start",
        status="succeeded",
        current_step_ids=["start"],
        checkpoint_ids=["cp-1"],
        events_path=tmp_path / "run-1" / "events.jsonl",
    )

    assert context.phase == ArtifactPublishPhase.START
    assert context.status == WorkflowStatus.SUCCEEDED
    assert context.current_step_ids == ["start"]
    assert context.checkpoint_ids == ["cp-1"]
    assert context.events_path == tmp_path / "run-1" / "events.jsonl"


def test_runtime_artifact_publisher_writes_start_artifacts(tmp_path) -> None:
    manifest = {"artifacts": {}}
    context = _context(
        tmp_path,
        phase=ArtifactPublishPhase.START,
        status=WorkflowStatus.RUNNING,
        manifest=manifest,
        initial_buffer_snapshot=DataBuffer({"request": {"topic": "ai"}}).snapshot(),
    )

    refs = RuntimeArtifactPublisher().publish(context)

    run_dir = tmp_path / "run-1"
    assert [ref.artifact_id for ref in refs] == [
        "request",
        "workflow_spec",
        "workflow_version",
        "data_buffer_initial",
    ]
    assert (run_dir / "request.json").exists()
    assert (run_dir / "workflow_spec.json").exists()
    assert (run_dir / "workflow_version.json").exists()
    assert (run_dir / "data_buffer.initial.json").exists()
    assert manifest["artifacts"]["request"] == "request.json"
    assert manifest["artifacts"]["data_buffer_initial"] == "data_buffer.initial.json"


def test_runtime_artifact_publisher_supports_start_and_terminal(tmp_path) -> None:
    publisher = RuntimeArtifactPublisher()

    assert publisher.supports(_context(tmp_path, phase=ArtifactPublishPhase.START)) is True
    assert publisher.supports(_context(tmp_path, phase=ArtifactPublishPhase.TERMINAL)) is True


@pytest.mark.parametrize(
    ("status", "terminal_key", "terminal_path"),
    [
        (WorkflowStatus.SUCCEEDED, "output", "output.json"),
        (WorkflowStatus.FAILED, "error", "error.json"),
        (WorkflowStatus.PAUSED, "pause", "pause.json"),
    ],
)
def test_runtime_artifact_publisher_writes_terminal_artifacts(
    tmp_path,
    status,
    terminal_key,
    terminal_path,
) -> None:
    manifest = _runtime_manifest(status=status)
    start_context = _context(
        tmp_path,
        phase=ArtifactPublishPhase.START,
        status=WorkflowStatus.RUNNING,
        manifest=manifest,
        initial_buffer_snapshot=DataBuffer({"request": {"topic": "ai"}}).snapshot(),
    )
    RuntimeArtifactPublisher().publish(start_context)
    (tmp_path / "run-1" / "events.jsonl").write_text("", encoding="utf-8")
    output = {"report": "done"} if status == WorkflowStatus.SUCCEEDED else {}
    context = _context(
        tmp_path,
        phase=ArtifactPublishPhase.TERMINAL,
        status=status,
        output=output,
        manifest=manifest,
        error=None if status != WorkflowStatus.FAILED else _workflow_error(),
        current_step_ids=["review"] if status == WorkflowStatus.PAUSED else [],
        checkpoint_ids=["cp-1"] if status == WorkflowStatus.PAUSED else [],
        final_buffer_snapshot=DataBuffer(output).snapshot(),
        buffer_diff=DataBuffer(output).diff(DataBuffer({}).snapshot()),
        metrics_payload={"status": status.value, "event_count": 3},
        redaction_report={"redacted": False},
    )

    refs = RuntimeArtifactPublisher().publish(context)

    run_dir = tmp_path / "run-1"
    artifact_ids = {ref.artifact_id for ref in refs}
    assert terminal_key in artifact_ids
    assert (run_dir / terminal_path).exists()
    assert (run_dir / "data_buffer.final.json").exists()
    assert (run_dir / "data_buffer.diff.json").exists()
    assert (run_dir / "step_results.json").exists()
    assert (run_dir / "metrics.json").exists()
    assert (run_dir / "redaction_report.json").exists()
    assert (run_dir / "manifest.json").exists()
    assert manifest["artifacts"][terminal_key] == terminal_path
    assert manifest["artifacts"]["data_buffer_final"] == "data_buffer.final.json"
    assert manifest["artifacts"]["data_buffer_diff"] == "data_buffer.diff.json"
    assert manifest["artifacts"]["step_results"] == "step_results.json"
    assert manifest["artifacts"]["metrics"] == "metrics.json"
    assert manifest["artifacts"]["redaction_report"] == "redaction_report.json"
    if status == WorkflowStatus.PAUSED:
        pause = __import__("json").loads((run_dir / "pause.json").read_text(encoding="utf-8"))
        assert pause["latest_checkpoint_id"] == "cp-1"


def test_artifact_publisher_registry_filters_and_publishes_in_order(tmp_path) -> None:
    calls: list[str] = []
    skipped = _FakePublisher("skipped", ArtifactPublishPhase.TERMINAL, calls)
    first = _FakePublisher("first", ArtifactPublishPhase.START, calls)
    second = _FakePublisher("second", ArtifactPublishPhase.START, calls)
    registry = ArtifactPublisherRegistry([skipped, first, second])
    context = _context(tmp_path, phase=ArtifactPublishPhase.START)

    refs = registry.publish_all(context)

    assert calls == ["first", "second"]
    assert [publisher.publisher_id for publisher in registry.registered_publishers()] == [
        "skipped",
        "first",
        "second",
    ]
    assert [ref.artifact_id for ref in refs] == ["first-ref", "second-ref"]


def test_workflow_artifact_publisher_registry_name_is_available(tmp_path) -> None:
    publisher = _FakePublisher("runtime", ArtifactPublishPhase.START, [])
    registry = WorkflowArtifactPublisherRegistry([publisher])

    assert registry.get("runtime") is publisher


def test_artifact_publisher_registry_rejects_duplicate_ids() -> None:
    publisher = _FakePublisher("runtime", ArtifactPublishPhase.START, [])
    registry = ArtifactPublisherRegistry([publisher])

    with pytest.raises(ValueError, match="artifact publisher already registered: runtime"):
        registry.register(publisher)


def test_artifact_publisher_registry_allows_distinct_artifacts(tmp_path) -> None:
    registry = ArtifactPublisherRegistry(
        [
            _StaticRefPublisher("report", "report_json", ArtifactPublishPhase.TERMINAL),
            _StaticRefPublisher("events", "events", ArtifactPublishPhase.TERMINAL),
        ]
    )

    refs = registry.publish_all(_context(tmp_path, phase=ArtifactPublishPhase.TERMINAL))

    assert [ref.artifact_id for ref in refs] == ["report_json", "events"]


def test_artifact_publisher_registry_rejects_duplicate_artifact_id(tmp_path) -> None:
    registry = ArtifactPublisherRegistry(
        [
            _StaticRefPublisher("report-a", "report_json", ArtifactPublishPhase.TERMINAL),
            _StaticRefPublisher("report-b", "report_json", ArtifactPublishPhase.TERMINAL),
        ]
    )

    with pytest.raises(ValueError, match="duplicate artifact id published: report_json"):
        registry.publish_all(_context(tmp_path, phase=ArtifactPublishPhase.TERMINAL))


def test_register_manifest_artifact_once_rejects_path_conflict() -> None:
    manifest = {"artifacts": {"report_markdown": "report.md"}}

    register_manifest_artifact_once(manifest, "report_markdown", "report.md")

    with pytest.raises(
        ValueError,
        match="manifest artifact key conflict: report_markdown report.md != reports/report.md",
    ):
        register_manifest_artifact_once(
            manifest,
            "report_markdown",
            "reports/report.md",
        )


def test_register_manifest_artifact_once_accepts_dict_artifact_record() -> None:
    manifest = {"artifacts": {"report_markdown": {"path": "report.md"}}}

    register_manifest_artifact_once(manifest, "report_markdown", "report.md")

    assert manifest["artifacts"]["report_markdown"] == "report.md"


def test_artifact_publisher_registry_rejects_missing_id() -> None:
    with pytest.raises(ValueError, match="non-empty publisher_id"):
        ArtifactPublisherRegistry([_MissingIdPublisher()])


def _context(
    tmp_path,
    *,
    phase: ArtifactPublishPhase | str = ArtifactPublishPhase.TERMINAL,
    status: WorkflowStatus | str = WorkflowStatus.SUCCEEDED,
    output: dict | None = None,
    manifest: dict | None = None,
    error=None,
    current_step_ids: list[str] | None = None,
    checkpoint_ids: list[str] | None = None,
    initial_buffer_snapshot=None,
    final_buffer_snapshot=None,
    buffer_diff=None,
    metrics_payload: dict | None = None,
    redaction_report: dict | None = None,
    events_path=None,
) -> ArtifactPublishContext:
    return ArtifactPublishContext(
        phase=phase,
        run_id="run-1",
        workflow=WorkflowSpec(
            workflow_id="publisher-test",
            name="Publisher Test",
            version="1.0",
            start_step_id="start",
            steps=[StepSpec("start", "test.start")],
        ),
        profile="test",
        status=status,
        request={"topic": "ai"},
        output=output or {},
        manifest=manifest or {"artifacts": {}},
        artifact_manager=ArtifactManager(tmp_path),
        step_results={},
        path=[],
        error=error,
        current_step_ids=current_step_ids,
        checkpoint_ids=checkpoint_ids,
        initial_buffer_snapshot=initial_buffer_snapshot,
        final_buffer_snapshot=final_buffer_snapshot,
        buffer_diff=buffer_diff,
        metrics_payload=metrics_payload,
        redaction_report=redaction_report,
        events_path=events_path,
    )


def _runtime_manifest(*, status: WorkflowStatus) -> dict:
    return {
        "schema_version": "newsroom.workflow_run_manifest.v1",
        "run_id": "run-1",
        "workflow_id": "publisher-test",
        "workflow_version": "1.0",
        "profile": "test",
        "status": status.value,
        "started_at": "2026-05-15T00:00:00Z",
        "finished_at": "2026-05-15T00:00:01Z",
        "path": [],
        "steps": {},
        "artifacts": {
            "request": "request.json",
            "workflow_spec": "workflow_spec.json",
            "workflow_version": "workflow_version.json",
            "events": "events.jsonl",
            "manifest": "manifest.json",
            "data_buffer_snapshot": "data_buffer_snapshot.json",
            "data_buffer_initial": "data_buffer.initial.json",
            "data_buffer_final": "data_buffer.final.json",
            "data_buffer_diff": "data_buffer.diff.json",
            "step_results": "step_results.json",
            "metrics": "metrics.json",
            "redaction_report": "redaction_report.json",
        },
    }


def _workflow_error():
    from core.framework.workflow import WorkflowError

    return WorkflowError(error_type="StepFailed", message="failed")


@dataclass
class _FakePublisher:
    publisher_id: str
    phase: ArtifactPublishPhase
    calls: list[str]

    def supports(self, context: ArtifactPublishContext) -> bool:
        return context.phase == self.phase

    def publish(self, context: ArtifactPublishContext) -> list[ArtifactRef]:
        self.calls.append(self.publisher_id)
        return [
            ArtifactRef(
                artifact_id=f"{self.publisher_id}-ref",
                run_id=context.run_id,
                artifact_type=self.publisher_id,
                path=f"{self.publisher_id}.json",
                content_type="application/json",
                size_bytes=2,
                checksum="{}",
                created_at=datetime(2026, 5, 15, tzinfo=UTC),
            )
        ]


@dataclass
class _StaticRefPublisher:
    publisher_id: str
    artifact_id: str
    phase: ArtifactPublishPhase

    def supports(self, context: ArtifactPublishContext) -> bool:
        return context.phase == self.phase

    def publish(self, context: ArtifactPublishContext) -> list[ArtifactRef]:
        return [
            ArtifactRef(
                artifact_id=self.artifact_id,
                run_id=context.run_id,
                artifact_type=self.publisher_id,
                path=f"{self.artifact_id}.json",
                content_type="application/json",
                size_bytes=2,
                checksum="{}",
                created_at=datetime(2026, 5, 15, tzinfo=UTC),
            )
        ]


class _MissingIdPublisher:
    def supports(self, context: ArtifactPublishContext) -> bool:
        return True

    def publish(self, context: ArtifactPublishContext) -> list[ArtifactRef]:
        return []
