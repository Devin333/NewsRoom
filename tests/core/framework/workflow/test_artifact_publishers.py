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
    StepOutcome,
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


def test_artifact_publisher_registry_rejects_duplicate_ids() -> None:
    publisher = _FakePublisher("runtime", ArtifactPublishPhase.START, [])
    registry = ArtifactPublisherRegistry([publisher])

    with pytest.raises(ValueError, match="already registered: runtime"):
        registry.register(publisher)


def test_artifact_publisher_registry_rejects_missing_id() -> None:
    with pytest.raises(ValueError, match="non-empty publisher_id"):
        ArtifactPublisherRegistry([_MissingIdPublisher()])


def _context(
    tmp_path,
    *,
    phase: ArtifactPublishPhase | str = ArtifactPublishPhase.TERMINAL,
    status: WorkflowStatus | str = WorkflowStatus.SUCCEEDED,
    current_step_ids: list[str] | None = None,
    checkpoint_ids: list[str] | None = None,
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
        output={},
        manifest={"artifacts": {}},
        artifact_manager=ArtifactManager(tmp_path),
        step_results={},
        path=[],
        current_step_ids=current_step_ids,
        checkpoint_ids=checkpoint_ids,
        events_path=events_path,
    )


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


class _MissingIdPublisher:
    def supports(self, context: ArtifactPublishContext) -> bool:
        return True

    def publish(self, context: ArtifactPublishContext) -> list[ArtifactRef]:
        return []
