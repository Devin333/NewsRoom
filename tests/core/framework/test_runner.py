import pytest

import core.framework.runner as runner_module
from core.framework import WorkflowRunner
from core.framework.specs import EdgeCondition, EdgeSpec, StepSpec, StepType, WorkflowSpec, WorkflowStatus
from core.framework.workflow import (
    FunctionStepRegistry,
    FunctionStepRunner,
    HumanReviewStepRunner,
    RUN_MANIFEST_SCHEMA_VERSION,
    StepRunnerRegistry,
    build_default_step_runner_registry,
)
from domain.sources import SourceError
from storage.artifacts import LocalJsonArtifactIndexStore
from storage.checkpoint import LocalJsonCheckpointStore
from storage.events import LocalJsonEventStore
from storage.security import REDACTED_VALUE


def test_workflow_runner_returns_stable_run_result(tmp_path) -> None:
    registry = FunctionStepRegistry()
    registry.register("sample.echo", lambda buffer: {"echo": buffer.read("request")})
    runner = WorkflowRunner(artifact_root=tmp_path, function_registry=registry)
    spec = WorkflowSpec(
        workflow_id="echo",
        name="Echo",
        version="1.0",
        start_step_id="echo",
        steps=[
            StepSpec(
                step_id="echo",
                implementation="sample.echo",
                read_keys=["request"],
                write_keys=["echo"],
                required_output_keys=["echo"],
            )
        ],
    )

    result = runner.run(spec, {"topic": "ai"}, profile="test", run_id="runner-success")

    assert result.status == WorkflowStatus.SUCCEEDED
    assert result.run_id == "runner-success"
    assert result.workflow_id == "echo"
    assert result.workflow_version == "1.0"
    assert result.output["echo"] == {"topic": "ai"}
    assert result.artifact_dir is not None
    assert result.manifest_path is not None
    assert result.events_path is not None
    assert result.to_dict()["status"] == "succeeded"

    artifact_refs = LocalJsonArtifactIndexStore(tmp_path / "_records" / "artifact_index").list_by_run(
        "runner-success"
    )
    artifact_types = {ref.artifact_type for ref in artifact_refs}
    assert {
        "request",
        "workflow_spec",
        "events",
        "manifest",
        "data_buffer_snapshot",
        "data_buffer_initial",
        "data_buffer_final",
        "data_buffer_diff",
        "output",
    }.issubset(artifact_types)
    output_ref = next(ref for ref in artifact_refs if ref.artifact_type == "output")
    assert output_ref.path == "output.json"
    assert output_ref.size_bytes is not None and output_ref.size_bytes > 0
    assert output_ref.checksum is not None

    event_store = LocalJsonEventStore(tmp_path / "_records" / "events")
    events = event_store.list_by_run("runner-success")
    assert [event.event_type for event in events] == [
        "workflow_started",
        "step_started",
        "step_succeeded",
        "workflow_succeeded",
    ]
    assert all(event.workflow_id == "echo" for event in events)
    assert [event.event_type for event in event_store.list_by_step("runner-success", "echo")] == [
        "step_started",
        "step_succeeded",
    ]


def test_workflow_runner_redacts_event_store_failure_payload(tmp_path) -> None:
    fake_secret = "sk" + "-runnersecret123456"
    registry = FunctionStepRegistry()
    registry.register(
        "sample.bad",
        lambda buffer: (_ for _ in ()).throw(RuntimeError(f"failed with {fake_secret}")),
    )
    runner = WorkflowRunner(artifact_root=tmp_path, function_registry=registry)
    spec = WorkflowSpec(
        workflow_id="redaction",
        name="Redaction",
        version="1.0",
        start_step_id="bad",
        steps=[
            StepSpec(
                step_id="bad",
                implementation="sample.bad",
                read_keys=[],
                write_keys=["output"],
                required_output_keys=["output"],
            )
        ],
    )

    result = runner.run(spec, {"topic": "ai"}, profile="test", run_id="runner-redaction")

    assert result.status == WorkflowStatus.FAILED
    failed_event = next(
        event
        for event in LocalJsonEventStore(tmp_path / "_records" / "events").list_by_run("runner-redaction")
        if event.event_type == "step_failed"
    )
    payload_text = str(failed_event.to_dict())
    assert fake_secret not in payload_text
    assert REDACTED_VALUE in payload_text
    report = failed_event.metadata["redaction_report"]
    assert "$.outcome.error_message" in report["redacted_fields"]
    assert "secret_like_string" in report["redaction_rules_applied"]


def test_workflow_runner_can_persist_checkpoints_when_injected(tmp_path) -> None:
    checkpoint_store = LocalJsonCheckpointStore(tmp_path / "checkpoints")
    registry = FunctionStepRegistry()
    registry.register("sample.echo", lambda buffer: {"echo": buffer.read("request")})
    runner = WorkflowRunner(
        artifact_root=tmp_path,
        function_registry=registry,
        checkpoint_store=checkpoint_store,
    )
    spec = WorkflowSpec(
        workflow_id="checkpoint-echo",
        name="Checkpoint Echo",
        version="1.0",
        start_step_id="echo",
        steps=[
            StepSpec(
                step_id="echo",
                implementation="sample.echo",
                read_keys=["request"],
                write_keys=["echo"],
                required_output_keys=["echo"],
            )
        ],
    )

    result = runner.run(spec, {"topic": "ai"}, profile="test", run_id="runner-checkpoint")

    assert result.status == WorkflowStatus.SUCCEEDED
    checkpoint = checkpoint_store.get_latest_checkpoint("runner-checkpoint")
    assert checkpoint is not None
    assert checkpoint.current_step_ids == []
    assert checkpoint.data_buffer_snapshot["echo"] == {"topic": "ai"}
    events = LocalJsonEventStore(tmp_path / "_records" / "events").list_by_run("runner-checkpoint")
    assert [event.event_type for event in events] == [
        "workflow_started",
        "step_started",
        "step_succeeded",
        "checkpoint_created",
        "workflow_succeeded",
    ]


def test_workflow_runner_resumes_from_checkpoint_after_step_failure(tmp_path) -> None:
    checkpoint_store = LocalJsonCheckpointStore(tmp_path / "checkpoints")
    write_should_fail = {"value": True}
    registry = FunctionStepRegistry()
    registry.register("sample.plan", lambda buffer: {"plan": buffer.read("request")["topic"]})

    def write_report(buffer):
        if write_should_fail["value"]:
            raise RuntimeError("writer crashed")
        return {"report": f"Report: {buffer.read('plan')}"}

    registry.register("sample.write", write_report)
    runner = WorkflowRunner(
        artifact_root=tmp_path,
        function_registry=registry,
        checkpoint_store=checkpoint_store,
    )
    spec = _resumable_two_step_spec()

    failed = runner.run(spec, {"topic": "ai"}, profile="test", run_id="runner-resume-source")

    assert failed.status == WorkflowStatus.FAILED
    checkpoint = next(
        item
        for item in checkpoint_store.list_checkpoints("runner-resume-source")
        if item.current_step_ids == ["write"]
    )

    write_should_fail["value"] = False
    resumed = runner.resume_from_checkpoint(
        spec,
        checkpoint,
        profile="test",
        run_id="runner-resumed-success",
    )

    assert resumed.status == WorkflowStatus.SUCCEEDED
    assert resumed.output["plan"] == "ai"
    assert resumed.output["report"] == "Report: ai"
    inspection = runner.inspect_run(
        "runner-resumed-success",
        verify_checksums=True,
        strict=True,
    )
    replay = runner.build_replay_bundle(
        "runner-resumed-success",
        verify_checksums=True,
        strict=True,
    )
    events = LocalJsonEventStore(tmp_path / "_records" / "events").list_by_run(
        "runner-resumed-success"
    )
    assert inspection.integrity.valid is True
    assert replay.integrity["valid"] is True
    assert replay.integrity["warnings"] == []
    assert replay.step_results["plan"]["outputs"]["plan"] == "ai"
    assert replay.step_results["write"]["outputs"]["report"] == "Report: ai"
    assert replay.step_results["artifact"]["artifacts"][0]["checksum"]
    assert replay.manifest["resumed_from_checkpoint_id"] == checkpoint.checkpoint_id
    assert [event.event_type for event in events][:2] == [
        "workflow_resumed",
        "checkpoint_restored",
    ]


def test_workflow_runner_resumes_human_review_after_approval(tmp_path) -> None:
    checkpoint_store = LocalJsonCheckpointStore(tmp_path / "checkpoints")
    functions = FunctionStepRegistry()
    functions.register(
        "sample.finalize",
        lambda buffer: {
            "report": (
                f"approved:{buffer.read('request')['topic']}:"
                f"{buffer.read('human_review_decision')['decision']}"
            )
        },
    )
    step_runners = StepRunnerRegistry.with_function_runner(FunctionStepRunner(functions))
    step_runners.register(StepType.HUMAN_REVIEW, HumanReviewStepRunner())
    runner = WorkflowRunner(
        artifact_root=tmp_path,
        step_runner_registry=step_runners,
        checkpoint_store=checkpoint_store,
    )
    spec = _human_review_resume_spec()

    paused = runner.run(spec, {"topic": "ai"}, profile="test", run_id="runner-human-paused")

    assert paused.status == WorkflowStatus.WAITING_FOR_HUMAN
    checkpoint = checkpoint_store.get_latest_checkpoint("runner-human-paused")
    assert checkpoint is not None
    assert checkpoint.current_step_ids == ["review"]

    resumed = runner.resume_from_checkpoint(
        spec,
        checkpoint,
        profile="test",
        run_id="runner-human-approved",
        buffer_updates={"human_review_decision": {"decision": "approved"}},
    )

    assert resumed.status == WorkflowStatus.SUCCEEDED
    assert resumed.output["report"] == "approved:ai:approved"
    inspection = runner.inspect_run("runner-human-approved", strict=True)
    replay = runner.build_replay_bundle("runner-human-approved", strict=True)
    assert inspection.integrity.valid is True
    assert replay.integrity["valid"] is True
    assert replay.manifest["resumed_from_checkpoint_id"] == checkpoint.checkpoint_id
    assert replay.step_results["review"]["next_hint"] == "human_approved"
    assert replay.step_results["finalize"]["outputs"]["report"] == "approved:ai:approved"


def test_workflow_runner_accepts_prebuilt_step_runner_registry(tmp_path) -> None:
    functions = FunctionStepRegistry()
    functions.register("sample.echo", lambda buffer: {"echo": buffer.read("request")})
    runner = WorkflowRunner(
        artifact_root=tmp_path,
        step_runner_registry=build_default_step_runner_registry(functions),
    )
    spec = WorkflowSpec(
        workflow_id="prebuilt-registry",
        name="Prebuilt Registry",
        version="1.0",
        start_step_id="echo",
        steps=[
            StepSpec(
                step_id="echo",
                implementation="sample.echo",
                read_keys=["request"],
                write_keys=["echo"],
                required_output_keys=["echo"],
            )
        ],
    )

    result = runner.run(spec, {"topic": "ai"}, profile="test", run_id="runner-prebuilt-registry")

    assert result.status == WorkflowStatus.SUCCEEDED
    assert result.output["echo"] == {"topic": "ai"}


def test_workflow_runner_requires_registry_or_function_registry(tmp_path) -> None:
    with pytest.raises(ValueError, match="function_registry is required"):
        WorkflowRunner(artifact_root=tmp_path)


def test_workflow_runner_default_registry_executes_artifact_step(tmp_path) -> None:
    runner = WorkflowRunner(artifact_root=tmp_path, function_registry=FunctionStepRegistry())
    spec = WorkflowSpec(
        workflow_id="artifact-step-default",
        name="Artifact Step Default",
        version="1.0",
        start_step_id="artifact",
        steps=[
            StepSpec(
                step_id="artifact",
                implementation="artifact.write",
                step_type=StepType.ARTIFACT,
                write_keys=["artifact_ref"],
                required_output_keys=["artifact_ref"],
                metadata={
                    "content": {"status": "ready"},
                    "relative_path": "steps/artifact/output.json",
                    "artifact_id": "artifact-output",
                },
            )
        ],
    )

    result = runner.run(spec, {}, profile="test", run_id="runner-default-artifact")

    assert result.status == WorkflowStatus.SUCCEEDED
    assert result.output["artifact_ref"]["artifact_id"] == "artifact-output"
    assert (tmp_path / "runner-default-artifact" / "steps" / "artifact" / "output.json").exists()
    artifact_refs = LocalJsonArtifactIndexStore(tmp_path / "_records" / "artifact_index").list_by_run(
        "runner-default-artifact"
    )
    assert any(
        ref.artifact_id == "step.artifact.step_output.artifact-output"
        and ref.path == "steps/artifact/output.json"
        for ref in artifact_refs
    )


def test_workflow_runner_uses_event_store_factory_by_default(tmp_path, monkeypatch) -> None:
    fake_store = _CollectingEventStore()
    monkeypatch.setattr(
        runner_module,
        "event_store_from_env",
        lambda *, artifact_root: fake_store,
    )
    registry = FunctionStepRegistry()
    registry.register("sample.echo", lambda buffer: {"echo": buffer.read("request")})
    runner = WorkflowRunner(artifact_root=tmp_path, function_registry=registry)
    spec = WorkflowSpec(
        workflow_id="factory-echo",
        name="Factory Echo",
        version="1.0",
        start_step_id="echo",
        steps=[
            StepSpec(
                step_id="echo",
                implementation="sample.echo",
                read_keys=["request"],
                write_keys=["echo"],
                required_output_keys=["echo"],
            )
        ],
    )

    runner.run(spec, {"topic": "ai"}, profile="test", run_id="factory-run")

    assert [event.event_type for event in fake_store.events] == [
        "workflow_started",
        "step_started",
        "step_succeeded",
        "workflow_succeeded",
    ]
    assert all(event.workflow_id == "factory-echo" for event in fake_store.events)


def test_workflow_runner_uses_artifact_index_factory_by_default(tmp_path, monkeypatch) -> None:
    fake_index = _CollectingArtifactIndex()
    monkeypatch.setattr(
        runner_module,
        "artifact_index_store_from_env",
        lambda *, artifact_root: fake_index,
    )
    registry = FunctionStepRegistry()
    registry.register("sample.echo", lambda buffer: {"echo": buffer.read("request")})
    runner = WorkflowRunner(artifact_root=tmp_path, function_registry=registry)
    spec = WorkflowSpec(
        workflow_id="artifact-factory-echo",
        name="Artifact Factory Echo",
        version="1.0",
        start_step_id="echo",
        steps=[
            StepSpec(
                step_id="echo",
                implementation="sample.echo",
                read_keys=["request"],
                write_keys=["echo"],
                required_output_keys=["echo"],
            )
        ],
    )

    runner.run(spec, {"topic": "ai"}, profile="test", run_id="artifact-factory-run")

    artifact_types = {ref.artifact_type for ref in fake_index.refs}
    assert {
        "request",
        "workflow_spec",
        "events",
        "manifest",
        "data_buffer_initial",
        "data_buffer_final",
        "data_buffer_diff",
        "output",
    }.issubset(artifact_types)
    assert all(ref.run_id == "artifact-factory-run" for ref in fake_index.refs)
    manifest_ref = next(ref for ref in fake_index.refs if ref.artifact_type == "manifest")
    assert manifest_ref.metadata["manifest_schema_version"] == RUN_MANIFEST_SCHEMA_VERSION


def test_workflow_runner_indexes_expanded_source_artifact_refs(tmp_path) -> None:
    registry = FunctionStepRegistry()
    registry.register(
        "sample.sources",
        lambda buffer: {
            "raw_items": [
                {
                    "source_id": "feed/source",
                    "source_item_id": "item-1",
                    "title": "Real source item",
                    "url": "https://example.com/item",
                    "raw_content": "<item>content</item>",
                }
            ],
            "source_errors": [
                SourceError(
                    source_id="feed/source",
                    source_name="Feed Source",
                    error_type="fetch_timeout",
                    error_message="timeout",
                    url="https://example.com/feed",
                )
            ],
        },
    )
    runner = WorkflowRunner(artifact_root=tmp_path, function_registry=registry)
    spec = WorkflowSpec(
        workflow_id="source-artifacts",
        name="Source Artifacts",
        version="1.0",
        start_step_id="sources",
        steps=[
            StepSpec(
                step_id="sources",
                implementation="sample.sources",
                read_keys=[],
                write_keys=["raw_items", "source_errors"],
                required_output_keys=["raw_items", "source_errors"],
            )
        ],
    )

    result = runner.run(spec, {}, profile="test", run_id="runner-source-artifacts")

    assert result.status == WorkflowStatus.SUCCEEDED
    refs = LocalJsonArtifactIndexStore(tmp_path / "_records" / "artifact_index").list_by_run(
        "runner-source-artifacts"
    )
    source_refs = {ref.artifact_type: ref for ref in refs if ref.artifact_type in {"source_item", "source_error"}}
    assert set(source_refs) == {"source_item", "source_error"}
    assert source_refs["source_item"].path == "sources/items/feed_source/item-1.json"
    assert source_refs["source_item"].checksum is not None
    assert source_refs["source_item"].metadata["source_id"] == "feed/source"
    assert source_refs["source_error"].path.startswith("sources/errors/feed_source/")
    assert source_refs["source_error"].checksum is not None
    assert source_refs["source_error"].metadata["source_artifact_type"] == "source_error"


def test_workflow_runner_uses_lineage_store_factory_by_default(tmp_path, monkeypatch) -> None:
    fake_lineage = _CollectingLineageStore()
    monkeypatch.setattr(
        runner_module,
        "lineage_store_from_env",
        lambda *, artifact_root: fake_lineage,
    )
    registry = FunctionStepRegistry()
    registry.register(
        "sample.evidence",
        lambda buffer: {
            "evidence_bundle": {
                "bundle_id": "bundle-1",
                "items": [
                    {
                        "evidence_id": "ev-1",
                        "source_url": "https://example.com/a",
                        "title": "Evidence",
                        "metadata": {"source_lineage": {"source_item_id": "raw-1"}},
                    }
                ],
            }
        },
    )
    runner = WorkflowRunner(artifact_root=tmp_path, function_registry=registry)
    spec = WorkflowSpec(
        workflow_id="lineage-factory",
        name="Lineage Factory",
        version="1.0",
        start_step_id="evidence",
        steps=[
            StepSpec(
                step_id="evidence",
                implementation="sample.evidence",
                read_keys=[],
                write_keys=["evidence_bundle"],
                required_output_keys=["evidence_bundle"],
            )
        ],
    )

    runner.run(spec, {}, profile="test", run_id="lineage-factory-run")

    assert len(fake_lineage.refs) == 2
    assert {ref.source_type for ref in fake_lineage.refs} == {"source_url", "source_item"}
    assert all(ref.run_id == "lineage-factory-run" for ref in fake_lineage.refs)


class _CollectingEventStore:
    def __init__(self) -> None:
        self.events = []

    def append_event(self, event):
        self.events.append(event)
        return len(self.events) - 1


class _CollectingArtifactIndex:
    def __init__(self) -> None:
        self.refs = []

    def index_artifact(self, ref):
        self.refs.append(ref)


class _CollectingLineageStore:
    def __init__(self) -> None:
        self.refs = []

    def record_many(self, refs):
        self.refs.extend(refs)
        return []


def _resumable_two_step_spec() -> WorkflowSpec:
    return WorkflowSpec(
        workflow_id="runner-resume",
        name="Runner Resume",
        version="1.0",
        start_step_id="plan",
        steps=[
            StepSpec(
                step_id="plan",
                implementation="sample.plan",
                read_keys=["request"],
                write_keys=["plan"],
                required_output_keys=["plan"],
            ),
            StepSpec(
                step_id="write",
                implementation="sample.write",
                read_keys=["plan"],
                write_keys=["report"],
                required_output_keys=["report"],
            ),
            StepSpec(
                step_id="artifact",
                implementation="artifact.write",
                step_type=StepType.ARTIFACT,
                read_keys=["report"],
                write_keys=["report_artifact"],
                required_output_keys=["report_artifact"],
                metadata={
                    "content_key": "report",
                    "relative_path": "steps/report/artifact.json",
                    "artifact_id": "resumed-report",
                    "output_key": "report_artifact",
                },
            ),
        ],
        edges=[
            EdgeSpec("plan-to-write", "plan", "write"),
            EdgeSpec("write-to-artifact", "write", "artifact"),
        ],
    )


def _human_review_resume_spec() -> WorkflowSpec:
    return WorkflowSpec(
        workflow_id="runner-human-review",
        name="Runner Human Review",
        version="1.0",
        start_step_id="review",
        input_schema={"properties": {"human_review_decision": {"type": "object"}}},
        steps=[
            StepSpec(
                step_id="review",
                implementation="human.review",
                step_type=StepType.HUMAN_REVIEW,
                read_keys=["request", "human_review_decision"],
                write_keys=["human_review_request"],
            ),
            StepSpec(
                step_id="finalize",
                implementation="sample.finalize",
                read_keys=["request", "human_review_decision"],
                write_keys=["report"],
                required_output_keys=["report"],
            ),
        ],
        edges=[
            EdgeSpec(
                "review-approved",
                "review",
                "finalize",
                condition=EdgeCondition.HUMAN_APPROVED,
            )
        ],
    )
