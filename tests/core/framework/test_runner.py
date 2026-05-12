import core.framework.runner as runner_module
from core.framework import WorkflowRunner
from core.framework.specs import StepSpec, WorkflowSpec, WorkflowStatus
from core.framework.workflow import FunctionStepRegistry
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
