from __future__ import annotations

from core.framework.specs import EdgeSpec, StepSpec, WorkflowSpec
from core.framework.workflow import (
    WorkflowCompileIssueCode,
    WorkflowCompileOptions,
    WorkflowCompiler,
)


def test_compile_fails_when_start_step_missing() -> None:
    result = WorkflowCompiler().compile(
        _spec(start_step_id="missing", terminal_step_ids=["finish"])
    )

    assert result.passed is False
    assert result.has_error(WorkflowCompileIssueCode.MISSING_START_STEP)


def test_compile_fails_when_step_id_is_duplicate() -> None:
    result = WorkflowCompiler().compile(
        _spec(steps=[*_base_steps(), StepSpec("finish", "sample.finish.again")])
    )

    assert result.passed is False
    assert result.has_error(WorkflowCompileIssueCode.DUPLICATE_STEP_ID)


def test_compile_fails_when_edge_source_is_unknown() -> None:
    result = WorkflowCompiler().compile(
        _spec(edges=[EdgeSpec("missing-finish", "missing", "finish")])
    )

    assert result.passed is False
    assert result.has_error(WorkflowCompileIssueCode.UNKNOWN_EDGE_SOURCE)


def test_compile_fails_when_edge_target_is_unknown() -> None:
    result = WorkflowCompiler().compile(
        _spec(edges=[EdgeSpec("start-missing", "start", "missing")])
    )

    assert result.passed is False
    assert result.has_error(WorkflowCompileIssueCode.UNKNOWN_EDGE_TARGET)


def test_compile_fails_when_terminal_step_is_unknown() -> None:
    result = WorkflowCompiler().compile(_spec(terminal_step_ids=["missing"]))

    assert result.passed is False
    assert result.has_error(WorkflowCompileIssueCode.UNKNOWN_TERMINAL_STEP)


def test_compile_warns_for_unreachable_step() -> None:
    result = WorkflowCompiler().compile(
        _spec(steps=[*_base_steps(), StepSpec("orphan", "sample.orphan")])
    )

    assert result.passed is True
    assert result.has_warning(WorkflowCompileIssueCode.UNREACHABLE_STEP)


def test_compile_strict_mode_treats_unreachable_step_as_error() -> None:
    result = WorkflowCompiler(options=WorkflowCompileOptions(strict=True)).compile(
        _spec(steps=[*_base_steps(), StepSpec("orphan", "sample.orphan")])
    )

    assert result.passed is False
    assert result.has_error(WorkflowCompileIssueCode.UNREACHABLE_STEP)


def test_compile_warns_when_terminal_step_has_outgoing_edge() -> None:
    result = WorkflowCompiler().compile(
        _spec(
            terminal_step_ids=["start"],
            edges=[EdgeSpec("start-finish", "start", "finish")],
        )
    )

    assert result.passed is True
    assert result.has_warning(WorkflowCompileIssueCode.TERMINAL_HAS_OUTGOING_EDGE)


def test_compile_fails_when_terminal_steps_are_missing() -> None:
    result = WorkflowCompiler().compile(_spec(terminal_step_ids=[]))

    assert result.passed is False
    assert result.has_error(WorkflowCompileIssueCode.NO_TERMINAL_STEP)


def test_compile_fails_when_cycle_has_no_max_step_visits() -> None:
    result = WorkflowCompiler().compile(_cyclic_spec(max_step_visits=0))

    assert result.passed is False
    assert result.has_error(WorkflowCompileIssueCode.CYCLE_REQUIRES_MAX_VISITS)
    assert result.graph is not None
    assert result.graph.has_cycle is True


def test_compile_allows_cycle_when_max_step_visits_is_set() -> None:
    result = WorkflowCompiler().compile(_cyclic_spec(max_step_visits=3))

    assert result.passed is True
    assert result.graph is not None
    assert result.graph.has_cycle is True


def _base_steps() -> list[StepSpec]:
    return [
        StepSpec("start", "sample.start", write_keys=["plan"]),
        StepSpec("finish", "sample.finish", read_keys=["plan"], write_keys=["report"]),
    ]


def _spec(
    *,
    start_step_id: str = "start",
    terminal_step_ids: list[str] | None = None,
    steps: list[StepSpec] | None = None,
    edges: list[EdgeSpec] | None = None,
) -> WorkflowSpec:
    return WorkflowSpec(
        workflow_id="compiler-graph",
        name="Compiler Graph",
        version="1.0",
        start_step_id=start_step_id,
        terminal_step_ids=terminal_step_ids if terminal_step_ids is not None else ["finish"],
        steps=steps or _base_steps(),
        edges=edges if edges is not None else [EdgeSpec("start-finish", "start", "finish")],
    )


def _cyclic_spec(*, max_step_visits: int) -> WorkflowSpec:
    return WorkflowSpec(
        workflow_id="compiler-cycle",
        name="Compiler Cycle",
        version="1.0",
        start_step_id="start",
        terminal_step_ids=["finish"],
        max_step_visits=max_step_visits,
        steps=_base_steps(),
        edges=[
            EdgeSpec("start-finish", "start", "finish"),
            EdgeSpec("finish-start", "finish", "start"),
        ],
    )
