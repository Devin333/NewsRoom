from __future__ import annotations

from core.framework.specs import EdgeSpec, StepSpec, WorkflowSpec
from core.framework.workflow import (
    WorkflowCompileIssueCode,
    WorkflowCompileOptions,
    WorkflowCompiler,
)


def test_compile_allows_read_keys_from_request() -> None:
    result = WorkflowCompiler(options=WorkflowCompileOptions(request_keys={"topic"})).compile(
        _single_step_spec(StepSpec("finish", "sample.finish", read_keys=["topic"], write_keys=["report"]))
    )

    assert result.passed is True


def test_compile_allows_read_keys_from_upstream_write_keys() -> None:
    result = WorkflowCompiler().compile(_linear_spec())

    assert result.passed is True
    assert result.read_write_plan.step_plans["finish"].upstream_write_keys == {"plan"}


def test_compile_allows_optional_read_keys() -> None:
    result = WorkflowCompiler().compile(
        _single_step_spec(
            StepSpec(
                "finish",
                "sample.finish",
                read_keys=["maybe_previous"],
                write_keys=["report"],
                metadata={"optional_read_keys": ["maybe_previous"]},
            )
        )
    )

    assert result.passed is True


def test_compile_allows_read_keys_from_resume_buffer() -> None:
    result = WorkflowCompiler(
        options=WorkflowCompileOptions(resume_buffer_keys={"checkpoint_state"})
    ).compile(
        _single_step_spec(
            StepSpec(
                "finish",
                "sample.finish",
                read_keys=["checkpoint_state"],
                write_keys=["report"],
            )
        )
    )

    assert result.passed is True


def test_compile_fails_when_read_key_is_unavailable() -> None:
    result = WorkflowCompiler().compile(
        _single_step_spec(
            StepSpec("finish", "sample.finish", read_keys=["missing"], write_keys=["report"])
        )
    )

    assert result.passed is False
    assert result.has_error(WorkflowCompileIssueCode.READ_KEY_UNAVAILABLE)


def test_compile_fails_when_step_writes_reserved_key() -> None:
    result = WorkflowCompiler().compile(
        _single_step_spec(StepSpec("finish", "sample.finish", write_keys=["run_id"]))
    )

    assert result.passed is False
    assert result.has_error(WorkflowCompileIssueCode.WRITE_KEY_RESERVED)


def test_compile_warns_when_step_writes_request_key() -> None:
    result = WorkflowCompiler(options=WorkflowCompileOptions(request_keys={"topic"})).compile(
        _single_step_spec(StepSpec("finish", "sample.finish", write_keys=["topic"]))
    )

    assert result.passed is True
    assert result.has_warning(WorkflowCompileIssueCode.WRITE_KEY_OVERLAPS_REQUEST)


def test_compile_fails_when_terminal_required_output_key_is_unsatisfied() -> None:
    result = WorkflowCompiler().compile(
        _single_step_spec(
            StepSpec(
                "finish",
                "sample.finish",
                write_keys=["draft"],
                required_output_keys=["report"],
            )
        )
    )

    assert result.passed is False
    assert result.has_error(WorkflowCompileIssueCode.REQUIRED_OUTPUT_KEY_UNSATISFIED)


def test_compile_warns_for_parallel_write_conflict() -> None:
    result = WorkflowCompiler().compile(
        WorkflowSpec(
            workflow_id="compiler-parallel",
            name="Compiler Parallel",
            version="1.0",
            start_step_id="start",
            terminal_step_ids=["left"],
            steps=[
                StepSpec("start", "sample.start"),
                StepSpec("left", "sample.left", write_keys=["score"]),
                StepSpec("right", "sample.right", write_keys=["score"]),
            ],
            edges=[
                EdgeSpec("start-left", "start", "left"),
                EdgeSpec("start-right", "start", "right"),
            ],
        )
    )

    assert result.passed is True
    assert result.has_warning(WorkflowCompileIssueCode.WRITE_KEY_CONFLICT)


def _single_step_spec(step: StepSpec) -> WorkflowSpec:
    return WorkflowSpec(
        workflow_id="compiler-dataflow",
        name="Compiler Dataflow",
        version="1.0",
        start_step_id=step.step_id,
        terminal_step_ids=[step.step_id],
        steps=[step],
    )


def _linear_spec() -> WorkflowSpec:
    return WorkflowSpec(
        workflow_id="compiler-linear",
        name="Compiler Linear",
        version="1.0",
        start_step_id="start",
        terminal_step_ids=["finish"],
        steps=[
            StepSpec("start", "sample.start", write_keys=["plan"]),
            StepSpec("finish", "sample.finish", read_keys=["plan"], write_keys=["report"]),
        ],
        edges=[EdgeSpec("start-finish", "start", "finish")],
    )
