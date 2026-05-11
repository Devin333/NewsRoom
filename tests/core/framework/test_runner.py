import core.framework.runner as runner_module
from core.framework import WorkflowRunner
from core.framework.specs import StepSpec, WorkflowSpec, WorkflowStatus
from core.framework.workflow import FunctionStepRegistry
from storage.artifacts import LocalJsonArtifactIndexStore
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


class _CollectingEventStore:
    def __init__(self) -> None:
        self.events = []

    def append_event(self, event):
        self.events.append(event)
        return len(self.events) - 1
