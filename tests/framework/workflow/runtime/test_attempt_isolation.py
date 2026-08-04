from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Any

import pytest

from framework.shared.attempts import current_attempt_context
from framework.specs import StepSpec, StepStatus, StepType
from framework.tool import ToolDefinition, ToolRegistry, ToolSideEffect
from framework.workflow.buffer import (
    BufferValueSchema,
    DataBuffer,
    DataBufferSchemaError,
    StaleWorkflowAttemptError,
    StepDataScope,
)
from framework.workflow.runners.base import (
    StepRunnerCapability,
    StepRunnerSideEffectLevel,
)
from framework.workflow.runners.function import FunctionStepRegistry
from framework.workflow.runners.parallel import ParallelGroupStepRunner
from framework.workflow.runners.registry import StepRunnerRegistry
from framework.workflow.runners.tool import ToolCallStepRunner
from framework.workflow.runners.tool_batch import ToolBatchStepRunner
from framework.workflow.runtime.result import StepOutcome
from framework.workflow.runtime.step_invoker import StepInvoker


class _LateWriteRunner:
    capability = StepRunnerCapability(
        step_type=StepType.FUNCTION,
        runner_id="test.late_write",
        version="1.0",
        supports_checkpoint=True,
        supports_resume=False,
        supports_timeout=True,
        supports_retry=True,
        side_effect_level=StepRunnerSideEffectLevel.NONE,
    )

    def __init__(self) -> None:
        self.release = threading.Event()
        self.finished = threading.Event()
        self.calls = 0
        self.late_error: BaseException | None = None

    def can_resolve(self, step: StepSpec) -> bool:
        return step.step_type == StepType.FUNCTION

    def validate_step(self, _step: StepSpec) -> list[Any]:
        return []

    def run(self, _step: StepSpec, buffer: Any) -> StepOutcome:
        self.calls += 1
        buffer.write("result", "staged-before-timeout")
        self.release.wait(1)
        try:
            buffer.write("result", "late-after-timeout")
        except BaseException as exc:  # noqa: BLE001 - asserted by the regression
            self.late_error = exc
        self.finished.set()
        return StepOutcome(status=StepStatus.SUCCEEDED, outputs={"result": "late"})


class _CooperativeRunner:
    def __init__(self, side_effect_level: StepRunnerSideEffectLevel) -> None:
        self.capability = StepRunnerCapability(
            step_type=StepType.FUNCTION,
            runner_id=f"test.{side_effect_level.value}",
            version="1.0",
            supports_checkpoint=True,
            supports_resume=False,
            supports_timeout=True,
            supports_retry=True,
            side_effect_level=side_effect_level,
        )
        self.contexts: list[tuple[str, str, int]] = []
        self.effects: list[str] = []

    def can_resolve(self, step: StepSpec) -> bool:
        return step.step_type == StepType.FUNCTION

    def validate_step(self, _step: StepSpec) -> list[Any]:
        return []

    def run(self, _step: StepSpec, buffer: Any) -> StepOutcome:
        context = current_attempt_context()
        assert context is not None
        self.contexts.append(
            (context.attempt_id, context.idempotency_key, context.fencing_token)
        )
        self.effects.append("called")
        if len(self.contexts) == 1:
            if "result" in buffer.list_allowed_writes():
                buffer.write("result", "discarded-first-attempt")
            assert context.cancel_event.wait(1)
            return StepOutcome(status=StepStatus.SUCCEEDED)
        if "result" in buffer.list_allowed_writes():
            buffer.write("result", "committed-second-attempt")
        return StepOutcome(
            status=StepStatus.SUCCEEDED,
            outputs={"result": "committed-second-attempt"},
        )


class _Recorder:
    def emit(self, *_args: Any, **_kwargs: Any) -> None:
        return None


class _RecordingArtifactManager:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.writes: list[str] = []

    def write_json(
        self,
        run_id: str,
        relative_path: str,
        _payload: dict[str, Any],
    ) -> Path:
        self.writes.append(relative_path)
        path = self.root / run_id / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{}", encoding="utf-8")
        return path


def _registry(runner: Any) -> StepRunnerRegistry:
    registry = StepRunnerRegistry()
    registry.register(StepType.FUNCTION, runner)
    return registry


def _buffer() -> DataBuffer:
    buffer = DataBuffer({"input": "value"})
    buffer.register_scope(
        StepDataScope(
            step_id="step",
            read_keys={"input"},
            write_keys={"result"},
        )
    )
    return buffer


def _run(step: StepSpec, runner: Any, buffer: DataBuffer) -> StepOutcome:
    return StepInvoker(
        step_runner_registry=_registry(runner),
        sleep_fn=lambda _delay: None,
        cancellation_grace_seconds=0.01,
    ).run_step_with_retries(
        step,
        buffer,
        _Recorder(),
    )


def test_timed_out_attempt_cannot_publish_staged_or_late_buffer_writes() -> None:
    runner = _LateWriteRunner()
    buffer = _buffer()
    version_before = buffer.snapshot(redacted=False).snapshot_version
    step = StepSpec(
        step_id="step",
        step_type=StepType.FUNCTION,
        read_keys=["input"],
        write_keys=["result"],
        timeout_policy={"timeout_seconds": 0.01, "on_timeout": "retry"},
        retry_policy={"max_retries": 1},
        metadata={"cancellation_grace_seconds": 0.005},
    )

    outcome = _run(step, runner, buffer)

    assert outcome.status == StepStatus.TIMEOUT
    assert outcome.error_details["termination_confirmed"] is False
    assert outcome.error_details["indeterminate"] is True
    assert runner.calls == 1
    assert buffer.exists("result") is False
    assert buffer.write_history() == []
    assert buffer.lineage("result") == []
    assert buffer.snapshot(redacted=False).snapshot_version == version_before

    runner.release.set()
    assert runner.finished.wait(1)
    assert isinstance(runner.late_error, StaleWorkflowAttemptError)
    assert buffer.exists("result") is False
    assert buffer.snapshot(redacted=False).snapshot_version == version_before


def test_confirmed_read_only_timeout_retries_and_commits_only_latest_overlay() -> None:
    runner = _CooperativeRunner(StepRunnerSideEffectLevel.READ_ONLY)
    buffer = _buffer()
    version_before = buffer.snapshot(redacted=False).snapshot_version
    step = StepSpec(
        step_id="step",
        step_type=StepType.FUNCTION,
        read_keys=["input"],
        write_keys=["result"],
        timeout_policy={"timeout_seconds": 0.01, "on_timeout": "retry"},
        retry_policy={"max_retries": 1},
        metadata={"cancellation_grace_seconds": 0.05},
    )

    outcome = _run(step, runner, buffer)

    assert outcome.status == StepStatus.SUCCEEDED
    assert buffer.read("result") == "committed-second-attempt"
    assert len(buffer.write_history("result")) == 1
    assert buffer.snapshot(redacted=False).snapshot_version == version_before + 1
    assert len(runner.contexts) == 2
    assert runner.contexts[0][0] != runner.contexts[1][0]
    assert runner.contexts[0][1] == runner.contexts[1][1]
    assert [item[2] for item in runner.contexts] == [1, 2]


def test_external_write_timeout_stops_after_confirmed_but_uncertain_outcome() -> None:
    runner = _CooperativeRunner(StepRunnerSideEffectLevel.EXTERNAL_WRITE)
    buffer = _buffer()
    step = StepSpec(
        step_id="step",
        step_type=StepType.FUNCTION,
        read_keys=["input"],
        write_keys=["result"],
        timeout_policy={"timeout_seconds": 0.01, "on_timeout": "retry"},
        retry_policy={"max_retries": 2},
        metadata={"cancellation_grace_seconds": 0.05},
    )

    outcome = _run(step, runner, buffer)

    assert outcome.status == StepStatus.TIMEOUT
    assert outcome.error_details["termination_confirmed"] is True
    assert outcome.error_details["indeterminate"] is True
    assert len(runner.contexts) == 1
    assert runner.effects == ["called"]
    assert buffer.exists("result") is False


def test_attempt_overlay_validates_schema_and_rejects_superseded_fence() -> None:
    buffer = DataBuffer()
    buffer.register_scope(
        StepDataScope(step_id="step", write_keys={"first", "second"})
    )
    buffer.register_schema(
        BufferValueSchema(
            key="first",
            value_type=dict,
            required_fields={"value"},
        )
    )
    old = buffer.begin_attempt("step", owner_id="old-owner")
    assert old.fencing_token == 1

    with pytest.raises(DataBufferSchemaError):
        old.write("first", {})

    current = buffer.begin_attempt("step", owner_id="current-owner")
    assert current.fencing_token == 2
    assert current.owner_id == "current-owner"
    with pytest.raises(StaleWorkflowAttemptError):
        old.write("second", "stale")

    version_before = buffer.snapshot(redacted=False).snapshot_version
    current.write("first", {"value": 1})
    current.write("second", "two")
    assert buffer.exists("first") is False
    current.commit()

    assert buffer.read("first") == {"value": 1}
    assert buffer.read("second") == "two"
    assert buffer.snapshot(redacted=False).snapshot_version == version_before + 1
    with pytest.raises(StaleWorkflowAttemptError):
        current.write("second", "late")


def test_tool_timeout_remains_step_timeout_and_discards_tool_outputs() -> None:
    tool_registry = ToolRegistry()
    tool_registry.register(
        ToolDefinition(
            name="sample.slow",
            side_effect=ToolSideEffect.READ_ONLY,
            timeout_seconds=0.01,
        ),
        lambda _arguments: time.sleep(0.2) or {"ok": True},
    )
    runner = ToolCallStepRunner(tool_registry)
    registry = StepRunnerRegistry()
    registry.register(StepType.TOOL_CALL, runner)
    buffer = DataBuffer()
    output_keys = {"step_tool_observation", "step_tool_result"}
    buffer.register_scope(
        StepDataScope(step_id="step", write_keys=output_keys)
    )
    step = StepSpec(
        step_id="step",
        step_type=StepType.TOOL_CALL,
        write_keys=sorted(output_keys),
        metadata={
            "tool_name": "sample.slow",
            "tool_policy": {
                "require_explicit_allowlist": False,
                "require_approval_for_side_effects": False,
                "cancellation_grace_seconds": 0.005,
            },
        },
    )

    outcome = StepInvoker(
        step_runner_registry=registry,
        sleep_fn=lambda _delay: None,
    ).run_step_with_retries(
        step,
        buffer,
        _Recorder(),
    )

    assert outcome.status == StepStatus.TIMEOUT
    assert outcome.error_details["termination_confirmed"] is False
    assert outcome.error_details["indeterminate"] is True
    assert all(not buffer.exists(key) for key in output_keys)


def test_nested_tool_and_step_share_one_total_attempt_budget_and_logical_key() -> None:
    tool_contexts: list[tuple[str, str, int]] = []

    def execute(_arguments: dict[str, object]) -> dict[str, bool]:
        context = current_attempt_context()
        assert context is not None
        tool_contexts.append(
            (context.attempt_id, context.idempotency_key, context.fencing_token)
        )
        if len(tool_contexts) == 1:
            raise RuntimeError("retry once")
        return {"ok": True}

    tool_registry = ToolRegistry()
    tool_registry.register(
        ToolDefinition(
            name="sample.retry",
            side_effect=ToolSideEffect.READ_ONLY,
            max_attempts=3,
        ),
        execute,
    )
    runner = ToolCallStepRunner(tool_registry)
    registry = StepRunnerRegistry()
    registry.register(StepType.TOOL_CALL, runner)
    output_keys = {"step_tool_observation", "step_tool_result"}
    buffer = DataBuffer()
    buffer.register_scope(
        StepDataScope(step_id="step", write_keys=output_keys)
    )
    step = StepSpec(
        step_id="step",
        step_type=StepType.TOOL_CALL,
        write_keys=sorted(output_keys),
        retry_policy={"max_retries": 1},
        metadata={
            "tool_name": "sample.retry",
            "tool_policy": {
                "require_explicit_allowlist": False,
                "require_approval_for_side_effects": False,
                "max_attempts_default": 3,
            },
        },
    )

    outcome = StepInvoker(
        step_runner_registry=registry,
        sleep_fn=lambda _delay: None,
    ).run_step_with_retries(
        step,
        buffer,
        _Recorder(),
    )

    assert outcome.status == StepStatus.SUCCEEDED
    assert outcome.metrics["attempt"] == 1
    assert len(tool_contexts) == 2
    assert tool_contexts[0][0] != tool_contexts[1][0]
    assert tool_contexts[0][1] == tool_contexts[1][1]
    assert [item[2] for item in tool_contexts] == [1, 2]


def test_nested_unconfirmed_tool_timeout_blocks_step_retry_and_overlap() -> None:
    release = threading.Event()
    started = threading.Event()
    finished = threading.Event()
    lock = threading.Lock()
    calls = 0
    active = 0
    max_active = 0
    effects: list[str] = []

    def execute(_arguments: dict[str, object]) -> dict[str, bool]:
        nonlocal calls, active, max_active
        with lock:
            calls += 1
            active += 1
            max_active = max(max_active, active)
        started.set()
        release.wait(1)
        effects.append("published")
        with lock:
            active -= 1
        finished.set()
        return {"ok": True}

    tool_registry = ToolRegistry()
    tool_registry.register(
        ToolDefinition(
            name="sample.nested_unconfirmed",
            side_effect=ToolSideEffect.WRITES_EXTERNAL_STATE,
            timeout_seconds=0.2,
            max_attempts=3,
        ),
        execute,
    )
    runner = ToolCallStepRunner(tool_registry)
    registry = StepRunnerRegistry()
    registry.register(StepType.TOOL_CALL, runner)
    output_keys = {"step_tool_observation", "step_tool_result"}
    buffer = DataBuffer()
    buffer.register_scope(StepDataScope(step_id="step", write_keys=output_keys))
    step = StepSpec(
        step_id="step",
        step_type=StepType.TOOL_CALL,
        write_keys=sorted(output_keys),
        retry_policy={"max_retries": 2},
        timeout_policy={"timeout_seconds": 0.01, "on_timeout": "retry"},
        metadata={
            "tool_name": "sample.nested_unconfirmed",
            "tool_policy": {
                "require_explicit_allowlist": False,
                "require_approval_for_side_effects": False,
                "cancellation_grace_seconds": 0.05,
            },
            "cancellation_grace_seconds": 0.005,
            "idempotency_contract": True,
            "reconciliation_supported": True,
        },
    )

    outcome = StepInvoker(
        step_runner_registry=registry,
        sleep_fn=lambda _delay: None,
    ).run_step_with_retries(
        step,
        buffer,
        _Recorder(),
    )

    assert started.is_set()
    assert outcome.status == StepStatus.TIMEOUT
    assert outcome.error_details["termination_confirmed"] is False
    assert outcome.error_details["indeterminate"] is True
    assert outcome.error_details["attempt"] == 1
    assert calls == 1
    assert max_active == 1
    assert effects == []
    assert all(not buffer.exists(key) for key in output_keys)

    release.set()
    assert finished.wait(1)
    assert effects == ["published"]
    assert calls == 1


def test_nested_external_write_failure_is_indeterminate_but_not_a_timeout() -> None:
    calls = 0
    effects: list[str] = []

    def execute(_arguments: dict[str, object]) -> dict[str, bool]:
        nonlocal calls
        calls += 1
        effects.append("accepted")
        raise RuntimeError("acknowledgement lost")

    tool_registry = ToolRegistry()
    tool_registry.register(
        ToolDefinition(
            name="sample.nested_publish_failure",
            side_effect=ToolSideEffect.WRITES_EXTERNAL_STATE,
            max_attempts=3,
        ),
        execute,
    )
    registry = StepRunnerRegistry()
    registry.register(StepType.TOOL_CALL, ToolCallStepRunner(tool_registry))
    output_keys = {"step_tool_observation", "step_tool_result"}
    buffer = DataBuffer()
    buffer.register_scope(StepDataScope(step_id="step", write_keys=output_keys))
    step = StepSpec(
        step_id="step",
        step_type=StepType.TOOL_CALL,
        write_keys=sorted(output_keys),
        retry_policy={"max_retries": 2},
        metadata={
            "tool_name": "sample.nested_publish_failure",
            "tool_policy": {
                "require_explicit_allowlist": False,
                "require_approval_for_side_effects": False,
            },
        },
    )

    outcome = StepInvoker(
        step_runner_registry=registry,
        sleep_fn=lambda _delay: None,
    ).run_step_with_retries(step, buffer, _Recorder())

    assert outcome.status == StepStatus.FAILED
    assert outcome.error_type == "WorkflowStepIndeterminateError"
    assert outcome.error_details["indeterminate"] is True
    assert outcome.error_details["termination_confirmed"] is True
    assert calls == 1
    assert effects == ["accepted"]
    assert all(not buffer.exists(key) for key in output_keys)


def test_parallel_branch_timeout_blocks_step_retry_overlap_and_artifacts(
    tmp_path: Path,
) -> None:
    release = threading.Event()
    started = threading.Event()
    finished = threading.Event()
    lock = threading.Lock()
    calls = 0
    active = 0
    max_active = 0
    effects: list[str] = []

    def blocking_branch(_buffer: Any) -> dict[str, bool]:
        nonlocal calls, active, max_active
        with lock:
            calls += 1
            active += 1
            max_active = max(max_active, active)
        started.set()
        release.wait(1)
        effects.append("published")
        with lock:
            active -= 1
        finished.set()
        return {"ok": True}

    function_registry = FunctionStepRegistry()
    function_registry.register("test.blocking_branch", blocking_branch)
    artifact_manager = _RecordingArtifactManager(tmp_path)
    registry = StepRunnerRegistry()
    registry.register(
        StepType.PARALLEL_GROUP,
        ParallelGroupStepRunner(
            function_registry,
            max_workers=1,
            artifact_manager=artifact_manager,
            run_id="run-indeterminate",
        ),
    )
    buffer = DataBuffer()
    buffer.register_scope(StepDataScope(step_id="step"))
    step = StepSpec(
        step_id="step",
        step_type=StepType.PARALLEL_GROUP,
        retry_policy={"max_retries": 1},
        timeout_policy={"timeout_seconds": 0.2, "on_timeout": "retry"},
        metadata={
            "branches": [
                {
                    "branch_id": "slow",
                    "implementation": "test.blocking_branch",
                    "timeout_seconds": 0.01,
                }
            ],
            "failure_strategy": "best_effort",
            "write_branch_artifacts": True,
            "cancellation_grace_seconds": 0.005,
        },
    )

    outcome = StepInvoker(
        step_runner_registry=registry,
        sleep_fn=lambda _delay: None,
    ).run_step_with_retries(
        step,
        buffer,
        _Recorder(),
    )

    assert started.is_set()
    assert outcome.status == StepStatus.TIMEOUT
    assert outcome.error_details["termination_confirmed"] is False
    assert outcome.error_details["indeterminate"] is True
    assert outcome.error_details["attempt"] == 1
    assert calls == 1
    assert max_active == 1
    assert effects == []
    assert artifact_manager.writes == []

    release.set()
    assert finished.wait(1)
    assert effects == ["published"]
    assert calls == 1


def test_parallel_branch_retries_claim_one_fixed_parent_budget() -> None:
    contexts: list[tuple[str, str, int, int, int]] = []

    def failing_branch(_buffer: Any) -> dict[str, bool]:
        context = current_attempt_context()
        assert context is not None
        assert context.budget is not None
        contexts.append(
            (
                context.attempt_id,
                context.idempotency_key,
                context.fencing_token,
                id(context.budget),
                context.budget.used,
            )
        )
        raise RuntimeError("branch failed")

    function_registry = FunctionStepRegistry()
    function_registry.register("test.failing_branch", failing_branch)
    registry = StepRunnerRegistry()
    registry.register(
        StepType.PARALLEL_GROUP,
        ParallelGroupStepRunner(function_registry, max_workers=1),
    )
    buffer = DataBuffer()
    buffer.register_scope(StepDataScope(step_id="step"))
    step = StepSpec(
        step_id="step",
        step_type=StepType.PARALLEL_GROUP,
        metadata={
            "branches": [
                {
                    "branch_id": "retrying",
                    "implementation": "test.failing_branch",
                    "retry_policy": {"max_retries": 3},
                }
            ],
            "failure_strategy": "all_success",
            "idempotency_contract": True,
            "reconciliation_supported": True,
        },
    )

    outcome = StepInvoker(
        step_runner_registry=registry,
        sleep_fn=lambda _delay: None,
    ).run_step_with_retries(step, buffer, _Recorder())

    assert outcome.status == StepStatus.FAILED
    assert len(contexts) == 4
    assert len({context[0] for context in contexts}) == 4
    assert len({context[1] for context in contexts}) == 1
    assert len({context[3] for context in contexts}) == 1
    assert [context[2] for context in contexts] == [1, 2, 3, 4]
    assert [context[4] for context in contexts] == [1, 2, 3, 4]


def test_parallel_external_branch_failure_does_not_retry_without_contract() -> None:
    effects: list[str] = []

    def failing_branch(_buffer: Any) -> dict[str, bool]:
        effects.append("accepted")
        raise RuntimeError("acknowledgement lost")

    function_registry = FunctionStepRegistry()
    function_registry.register("test.unsafe_branch", failing_branch)
    registry = StepRunnerRegistry()
    registry.register(
        StepType.PARALLEL_GROUP,
        ParallelGroupStepRunner(function_registry, max_workers=1),
    )
    buffer = DataBuffer()
    buffer.register_scope(StepDataScope(step_id="step"))
    step = StepSpec(
        step_id="step",
        step_type=StepType.PARALLEL_GROUP,
        metadata={
            "branches": [
                {
                    "branch_id": "unsafe",
                    "implementation": "test.unsafe_branch",
                    "retry_policy": {"max_retries": 3},
                }
            ],
            "failure_strategy": "all_success",
        },
    )

    outcome = StepInvoker(
        step_runner_registry=registry,
        sleep_fn=lambda _delay: None,
    ).run_step_with_retries(step, buffer, _Recorder())

    assert outcome.status == StepStatus.FAILED
    assert outcome.error_type == "WorkflowStepIndeterminateError"
    assert outcome.error_details["indeterminate"] is True
    assert effects == ["accepted"]


def test_tool_batch_workers_share_step_context_and_total_attempt_budget() -> None:
    barrier = threading.Barrier(2)
    lock = threading.Lock()
    contexts: dict[str, tuple[str, str, int, int, int]] = {}

    def execute(name: str) -> Any:
        def _execute(_arguments: dict[str, object]) -> dict[str, str]:
            context = current_attempt_context()
            assert context is not None
            assert context.budget is not None
            with lock:
                contexts[name] = (
                    context.attempt_id,
                    context.idempotency_key,
                    context.fencing_token,
                    id(context.budget),
                    context.budget.used,
                )
            barrier.wait(1)
            return {"name": name}

        return _execute

    tool_registry = ToolRegistry()
    for name in ("sample.batch_one", "sample.batch_two"):
        tool_registry.register(
            ToolDefinition(
                name=name,
                side_effect=ToolSideEffect.READ_ONLY,
                concurrency_safe=True,
                max_attempts=1,
            ),
            execute(name),
        )
    runner = ToolBatchStepRunner(tool_registry, max_workers=2)
    registry = StepRunnerRegistry()
    registry.register(StepType.TOOL_BATCH, runner)
    output_keys = {"tool_observations", "tool_results"}
    buffer = DataBuffer()
    buffer.register_scope(StepDataScope(step_id="step", write_keys=output_keys))
    step = StepSpec(
        step_id="step",
        step_type=StepType.TOOL_BATCH,
        write_keys=sorted(output_keys),
        metadata={
            "tool_calls": [
                {"tool_name": "sample.batch_one", "call_id": "batch-one"},
                {"tool_name": "sample.batch_two", "call_id": "batch-two"},
            ],
            "tool_policy": {
                "require_explicit_allowlist": False,
                "require_approval_for_side_effects": False,
            },
        },
    )

    outcome = StepInvoker(
        step_runner_registry=registry,
        sleep_fn=lambda _delay: None,
    ).run_step_with_retries(
        step,
        buffer,
        _Recorder(),
    )

    assert outcome.status == StepStatus.SUCCEEDED
    assert set(contexts) == {"sample.batch_one", "sample.batch_two"}
    first, second = contexts.values()
    assert first[0] != second[0]
    assert first[1] != second[1]
    assert first[1].startswith(f"{outcome.metrics['idempotency_key']}:tool:")
    assert second[1].startswith(f"{outcome.metrics['idempotency_key']}:tool:")
    assert first[2] == second[2] == 1
    assert first[3] == second[3]
    assert first[4] == second[4] == 1


def test_tool_batch_and_step_retries_share_one_total_attempt_budget() -> None:
    contexts: list[tuple[str, str, int, int]] = []
    calls = 0

    def execute(_arguments: dict[str, object]) -> dict[str, bool]:
        nonlocal calls
        calls += 1
        context = current_attempt_context()
        assert context is not None
        assert context.budget is not None
        contexts.append(
            (
                context.attempt_id,
                context.idempotency_key,
                context.fencing_token,
                id(context.budget),
            )
        )
        raise RuntimeError("always fails")

    tool_registry = ToolRegistry()
    tool_registry.register(
        ToolDefinition(
            name="sample.batch_retry_budget",
            side_effect=ToolSideEffect.READ_ONLY,
            concurrency_safe=True,
            max_attempts=2,
        ),
        execute,
    )
    runner = ToolBatchStepRunner(tool_registry, max_workers=1)
    registry = StepRunnerRegistry()
    registry.register(StepType.TOOL_BATCH, runner)
    output_keys = {"tool_observations", "tool_results"}
    buffer = DataBuffer()
    buffer.register_scope(StepDataScope(step_id="step", write_keys=output_keys))
    step = StepSpec(
        step_id="step",
        step_type=StepType.TOOL_BATCH,
        write_keys=sorted(output_keys),
        retry_policy={"max_retries": 1},
        metadata={
            "tool_calls": [
                {
                    "tool_name": "sample.batch_retry_budget",
                    "call_id": "batch-retry-budget",
                }
            ],
            "tool_policy": {
                "require_explicit_allowlist": False,
                "require_approval_for_side_effects": False,
            },
        },
    )

    outcome = StepInvoker(
        step_runner_registry=registry,
        sleep_fn=lambda _delay: None,
    ).run_step_with_retries(
        step,
        buffer,
        _Recorder(),
    )

    assert outcome.status == StepStatus.FAILED
    assert outcome.error_type == "ToolBatchStepFailed"
    assert outcome.metrics["attempt"] == 1
    assert calls == 2
    assert len(contexts) == 2
    assert contexts[0][0] != contexts[1][0]
    assert contexts[0][1] == contexts[1][1]
    assert contexts[0][1].startswith(f"{outcome.metrics['idempotency_key']}:tool:")
    assert [context[2] for context in contexts] == [1, 2]
    assert contexts[0][3] == contexts[1][3]


def test_tool_only_retry_uses_fixed_shared_budget_without_step_retry() -> None:
    contexts: list[tuple[str, str, int, int]] = []

    def execute(_arguments: dict[str, object]) -> dict[str, bool]:
        context = current_attempt_context()
        assert context is not None
        assert context.budget is not None
        contexts.append(
            (
                context.attempt_id,
                context.idempotency_key,
                context.fencing_token,
                id(context.budget),
            )
        )
        if len(contexts) == 1:
            raise RuntimeError("retry in ToolRuntime only")
        return {"ok": True}

    tool_registry = ToolRegistry()
    tool_registry.register(
        ToolDefinition(
            name="sample.tool_only_retry",
            side_effect=ToolSideEffect.READ_ONLY,
            max_attempts=2,
        ),
        execute,
    )
    runner = ToolCallStepRunner(tool_registry)
    registry = StepRunnerRegistry()
    registry.register(StepType.TOOL_CALL, runner)
    output_keys = {"step_tool_observation", "step_tool_result"}
    buffer = DataBuffer()
    buffer.register_scope(StepDataScope(step_id="step", write_keys=output_keys))
    step = StepSpec(
        step_id="step",
        step_type=StepType.TOOL_CALL,
        write_keys=sorted(output_keys),
        retry_policy={"max_retries": 0},
        metadata={
            "tool_name": "sample.tool_only_retry",
            "tool_policy": {
                "require_explicit_allowlist": False,
                "require_approval_for_side_effects": False,
            },
        },
    )

    outcome = StepInvoker(
        step_runner_registry=registry,
        sleep_fn=lambda _delay: None,
    ).run_step_with_retries(
        step,
        buffer,
        _Recorder(),
    )

    assert outcome.status == StepStatus.SUCCEEDED
    assert outcome.metrics["attempt"] == 1
    assert len(contexts) == 2
    assert contexts[0][0] != contexts[1][0]
    assert contexts[0][1] == contexts[1][1]
    assert contexts[0][1].startswith(f"{outcome.metrics['idempotency_key']}:tool:")
    assert [context[2] for context in contexts] == [1, 2]
    assert contexts[0][3] == contexts[1][3]
    assert buffer.read("step_tool_result")["retry_count"] == 1
