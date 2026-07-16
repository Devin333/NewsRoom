from __future__ import annotations

import json
from pathlib import Path

import pytest

from framework import WorkflowRunner
from framework.events.errors import EventContractError, EventStoreUnavailableError
from framework.events.runtime.models import EventPage
from framework.specs import EdgeSpec, StepSpec, WorkflowSpec
from framework.workflow import FunctionStepRegistry
from framework.workflow.buffer import StepScopedDataBufferView
from infrastructure.storage.events.factory import durable_event_storage_from_env


@pytest.mark.parametrize("projection_mutation", ["delete", "tamper"])
def test_runner_inspection_views_use_durable_events(
    tmp_path,
    projection_mutation,
) -> None:
    runner, storage = _runner(tmp_path)
    result = runner.run(
        _workflow("workflow-one", step_ids=("step-1",)),
        {},
        profile="test",
        run_id="run-1",
    )
    projection_path = Path(result.artifact_dir) / "events.jsonl"
    if projection_mutation == "delete":
        projection_path.unlink()
    else:
        projection_path.write_text(
            json.dumps(
                {
                    "event_id": "projection-only",
                    "event_type": "workflow_failed",
                    "run_id": "run-1",
                    "payload": {"path": [], "error": {"error_type": "forged"}},
                }
            )
            + "\n",
            encoding="utf-8",
        )
    durable_count = storage.event_store.get_stream_high_watermark("run:run-1")
    assert durable_count is not None

    inspection = runner.inspect_run("run-1", strict=True)
    replay = runner.build_replay_bundle("run-1", strict=True)
    content = runner.build_replay_content_bundle("run-1")
    diagnostics = runner.inspect_run_diagnostics("run-1", strict=True)
    health = runner.inspect_run_health("run-1", strict=True)

    assert inspection.event_summary is not None
    assert inspection.event_summary.event_count == durable_count
    assert len(replay.events) == durable_count
    assert len(content.events) == durable_count
    assert content.events[0]["event_id"] != "projection-only"
    assert diagnostics.timeline_summary is not None
    assert diagnostics.timeline_summary.event_count == durable_count
    assert health.event_count == durable_count
    projection_artifact = content.artifact_by_key("events")
    assert projection_artifact is not None
    assert projection_artifact.content is None


def test_runner_compare_reads_each_durable_run_stream(tmp_path) -> None:
    runner, storage = _runner(tmp_path)
    base = runner.run(
        _workflow("workflow-one", step_ids=("step-1",)),
        {},
        profile="test",
        run_id="run-base",
    )
    target = runner.run(
        _workflow("workflow-two", step_ids=("step-1", "step-2")),
        {},
        profile="test",
        run_id="run-target",
    )
    (Path(base.artifact_dir) / "events.jsonl").write_text(
        "{not-json\n",
        encoding="utf-8",
    )
    (Path(target.artifact_dir) / "events.jsonl").unlink()
    base_count = storage.event_store.get_stream_high_watermark("run:run-base")
    target_count = storage.event_store.get_stream_high_watermark("run:run-target")
    assert base_count is not None
    assert target_count is not None

    comparison = runner.compare_runs("run-base", "run-target", strict=True)

    assert comparison.event_count_delta == target_count - base_count
    assert comparison.event_count_delta > 0


def test_runner_inspection_views_fail_when_durable_store_is_unavailable(
    tmp_path,
) -> None:
    runner, _ = _runner(tmp_path)
    workflow = _workflow("workflow-one", step_ids=("step-1",))
    runner.run(workflow, {}, profile="test", run_id="run-1")
    runner.run(workflow, {}, profile="test", run_id="run-2")
    runner._event_reader = _UnavailableEventReader()

    operations = (
        lambda: runner.inspect_run("run-1"),
        lambda: runner.build_replay_bundle("run-1"),
        lambda: runner.build_replay_content_bundle("run-1"),
        lambda: runner.inspect_run_diagnostics("run-1"),
        lambda: runner.inspect_run_health("run-1"),
        lambda: runner.compare_runs("run-1", "run-2"),
    )
    for operation in operations:
        with pytest.raises(EventStoreUnavailableError):
            operation()


@pytest.mark.parametrize("failure", ["cross_scope", "watermark_change", "gap"])
def test_runner_inspection_rejects_invalid_durable_pages(tmp_path, failure) -> None:
    runner, _ = _runner(tmp_path)
    runner.run(
        _workflow("workflow-one", step_ids=("step-1",)),
        {},
        profile="test",
        run_id="run-1",
    )
    runner._event_reader = _InvalidEventReader(runner._event_reader, failure)

    with pytest.raises(EventContractError, match="durable run event reader"):
        runner.inspect_run("run-1")


def _runner(root):
    artifact_root = root / "runs"
    storage = durable_event_storage_from_env(
        artifact_root=artifact_root,
        env={},
    )
    registry = FunctionStepRegistry()
    registry.register("test.step", _step)
    return (
        WorkflowRunner(
            artifact_root=artifact_root,
            function_registry=registry,
            event_runtime=storage.event_runtime,
            event_reader=storage.event_store,
            event_schema_catalog=storage.schema_catalog,
        ),
        storage,
    )


def _workflow(workflow_id: str, *, step_ids: tuple[str, ...]) -> WorkflowSpec:
    steps = [
        StepSpec(
            step_id,
            implementation="test.step",
        )
        for step_id in step_ids
    ]
    edges = [
        EdgeSpec(
            f"{source}-to-{target}",
            source,
            target,
        )
        for source, target in zip(step_ids, step_ids[1:])
    ]
    return WorkflowSpec(
        workflow_id=workflow_id,
        name=workflow_id,
        version="1",
        steps=steps,
        edges=edges,
        terminal_step_ids=[step_ids[-1]],
    )


def _step(_buffer: StepScopedDataBufferView) -> dict[str, object]:
    return {}


class _UnavailableEventReader:
    def get_stream_high_watermark(self, stream_id, *, tenant_id=None):
        raise EventStoreUnavailableError("durable store unavailable")

    def read_stream(self, request):
        raise AssertionError("read_stream must not run after watermark failure")


class _InvalidEventReader:
    def __init__(self, delegate, failure) -> None:
        self._delegate = delegate
        self._failure = failure

    def get_stream_high_watermark(self, stream_id, *, tenant_id=None):
        return self._delegate.get_stream_high_watermark(
            stream_id,
            tenant_id=tenant_id,
        )

    def read_stream(self, request):
        page = self._delegate.read_stream(request)
        if self._failure == "cross_scope":
            return object()
        if self._failure == "watermark_change":
            return EventPage(
                stream_id=page.stream_id,
                events=page.events,
                high_watermark=page.high_watermark + 1,
                tenant_id=page.tenant_id,
            )
        return EventPage(
            stream_id=page.stream_id,
            events=page.events[1:],
            high_watermark=page.high_watermark,
            tenant_id=page.tenant_id,
        )
