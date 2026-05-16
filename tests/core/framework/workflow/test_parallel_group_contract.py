from __future__ import annotations

from core.framework.specs import StepSpec, StepStatus, StepType
from core.framework.workflow import DataBuffer, FunctionStepRegistry, ParallelGroupStepRunner


def _runner(functions: FunctionStepRegistry | None = None) -> ParallelGroupStepRunner:
    return ParallelGroupStepRunner(functions or FunctionStepRegistry(), max_workers=4)


def _run_parallel(
    runner: ParallelGroupStepRunner,
    *,
    metadata: dict,
    write_keys: list[str] | None = None,
    required_output_keys: list[str] | None = None,
    buffer: DataBuffer | None = None,
):
    data_buffer = buffer or DataBuffer()
    step = StepSpec(
        "parallel",
        "parallel.contract",
        step_type=StepType.PARALLEL_GROUP,
        write_keys=write_keys or ["left", "right", "items", "branches", "branch_results", "summary"],
        required_output_keys=required_output_keys or [],
        metadata=metadata,
    )
    return runner.run(
        step,
        data_buffer.scope(read_keys=["request"], write_keys=step.write_keys),
    )


def test_parallel_group_runs_multiple_branches() -> None:
    functions = FunctionStepRegistry()
    functions.register("branch.left", lambda buffer: {"left": buffer.read("request")["topic"]})
    functions.register("branch.right", lambda buffer: {"right": "R"})
    buffer = DataBuffer({"request": {"topic": "ai"}})

    outcome = _run_parallel(
        _runner(functions),
        metadata={
            "branches": [
                {
                    "branch_id": "left",
                    "implementation": "branch.left",
                    "read_keys": ["request"],
                    "write_keys": ["left"],
                },
                {"branch_id": "right", "implementation": "branch.right", "write_keys": ["right"]},
            ],
        },
        write_keys=["left", "right"],
        buffer=buffer,
    )

    assert outcome.status == StepStatus.SUCCEEDED
    assert buffer.read("left") == "ai"
    assert buffer.read("right") == "R"
    assert outcome.metrics["branch_count"] == 2
    assert outcome.metrics["success_count"] == 2


def test_parallel_group_rejects_non_dict_branch() -> None:
    outcome = _run_parallel(
        _runner(),
        metadata={"branches": ["not-a-branch"]},
    )

    assert outcome.status == StepStatus.FAILED
    assert "branch must be an object" in outcome.error_message


def test_parallel_group_rejects_branch_without_implementation() -> None:
    outcome = _run_parallel(
        _runner(),
        metadata={"branches": [{"branch_id": "missing_impl", "write_keys": ["left"]}]},
    )

    assert outcome.status == StepStatus.FAILED
    assert "implementation is required" in outcome.error_message


def test_parallel_group_rejects_non_dict_branch_output() -> None:
    functions = FunctionStepRegistry()
    functions.register("branch.bad", lambda buffer: ["not", "a", "dict"])

    outcome = _run_parallel(
        _runner(functions),
        metadata={
            "branches": [
                {"branch_id": "bad", "implementation": "branch.bad", "write_keys": ["items"]}
            ]
        },
    )

    assert outcome.status == StepStatus.FAILED
    assert "expected dict" in outcome.error_message


def test_parallel_group_rejects_missing_required_output_keys() -> None:
    functions = FunctionStepRegistry()
    functions.register("branch.bad", lambda buffer: {"other": 1})

    outcome = _run_parallel(
        _runner(functions),
        metadata={
            "branches": [
                {
                    "branch_id": "bad",
                    "implementation": "branch.bad",
                    "write_keys": ["items"],
                    "required_output_keys": ["items"],
                }
            ]
        },
    )

    assert outcome.status == StepStatus.FAILED
    assert "missing required outputs" in outcome.error_message


def test_parallel_group_records_branch_results() -> None:
    functions = FunctionStepRegistry()
    functions.register("branch.left", lambda buffer: {"left": "L"})
    functions.register("branch.right", lambda buffer: {"right": "R"})
    buffer = DataBuffer()

    outcome = _run_parallel(
        _runner(functions),
        metadata={
            "branch_results_key": "branch_results",
            "branches": [
                {
                    "branch_id": "left",
                    "implementation": "branch.left",
                    "write_keys": ["left"],
                },
                {
                    "branch_id": "right",
                    "implementation": "branch.right",
                    "write_keys": ["right"],
                },
            ],
        },
        write_keys=["left", "right", "branch_results"],
        buffer=buffer,
    )

    assert outcome.status == StepStatus.SUCCEEDED
    branch_results = buffer.read("branch_results")
    assert {
        (result["branch_id"], result["implementation"], result["status"])
        for result in branch_results
    } == {
        ("left", "branch.left", "succeeded"),
        ("right", "branch.right", "succeeded"),
    }
    assert {result["branch_id"]: result["outputs"] for result in branch_results} == {
        "left": {"left": "L"},
        "right": {"right": "R"},
    }


def test_parallel_group_requires_unique_branch_ids() -> None:
    functions = FunctionStepRegistry()
    functions.register("branch.one", lambda buffer: {"items": ["one"]})
    functions.register("branch.two", lambda buffer: {"items": ["two"]})

    outcome = _run_parallel(
        _runner(functions),
        metadata={
            "branches": [
                {"branch_id": "dup", "implementation": "branch.one", "write_keys": ["items"]},
                {"branch_id": "dup", "implementation": "branch.two", "write_keys": ["items"]},
            ],
        },
    )

    assert outcome.status == StepStatus.FAILED
    assert "branch_id must be unique" in outcome.error_message


def test_parallel_group_derives_branch_id_from_implementation() -> None:
    functions = FunctionStepRegistry()
    functions.register("branch.left", lambda buffer: {"left": "L"})
    buffer = DataBuffer()

    outcome = _run_parallel(
        _runner(functions),
        metadata={
            "branch_results_key": "branch_results",
            "branches": [{"implementation": "branch.left", "write_keys": ["left"]}],
        },
        write_keys=["left", "branch_results"],
        buffer=buffer,
    )

    assert outcome.status == StepStatus.SUCCEEDED
    assert buffer.read("branch_results")[0]["branch_id"] == "branch.left"


def test_parallel_group_rejects_invalid_branch_id() -> None:
    functions = FunctionStepRegistry()
    functions.register("branch.left", lambda buffer: {"left": "L"})

    outcome = _run_parallel(
        _runner(functions),
        metadata={
            "branches": [
                {"branch_id": "bad branch", "implementation": "branch.left", "write_keys": ["left"]}
            ]
        },
    )

    assert outcome.status == StepStatus.FAILED
    assert "branch_id must contain only" in outcome.error_message


def test_parallel_group_conflict_strategy_error_fails_on_duplicate_output() -> None:
    functions = FunctionStepRegistry()
    functions.register("branch.left", lambda buffer: {"items": ["left"]})
    functions.register("branch.right", lambda buffer: {"items": ["right"]})

    outcome = _run_parallel(
        _runner(functions),
        metadata={
            "conflict_strategy": "error",
            "branches": [
                {"branch_id": "left", "implementation": "branch.left", "write_keys": ["items"]},
                {"branch_id": "right", "implementation": "branch.right", "write_keys": ["items"]},
            ],
        },
    )

    assert outcome.status == StepStatus.FAILED
    assert "output conflict" in outcome.error_message


def test_parallel_group_conflict_strategy_namespace_isolates_outputs() -> None:
    functions = FunctionStepRegistry()
    functions.register("branch.left", lambda buffer: {"items": ["left"]})
    functions.register("branch.right", lambda buffer: {"items": ["right"]})
    buffer = DataBuffer()

    outcome = _run_parallel(
        _runner(functions),
        metadata={
            "conflict_strategy": "namespace",
            "branches": [
                {"branch_id": "left", "implementation": "branch.left", "write_keys": ["items"]},
                {"branch_id": "right", "implementation": "branch.right", "write_keys": ["items"]},
            ],
        },
        write_keys=["branches"],
        required_output_keys=["branches"],
        buffer=buffer,
    )

    assert outcome.status == StepStatus.SUCCEEDED
    assert buffer.read("branches") == {
        "left": {"items": ["left"]},
        "right": {"items": ["right"]},
    }


def test_parallel_group_conflict_strategy_last_write_allows_override() -> None:
    functions = FunctionStepRegistry()
    functions.register("branch.left", lambda buffer: {"items": ["left"]})
    functions.register("branch.right", lambda buffer: {"items": ["right"]})
    buffer = DataBuffer()

    outcome = _run_parallel(
        ParallelGroupStepRunner(functions, max_workers=1),
        metadata={
            "conflict_strategy": "last_write",
            "branches": [
                {"branch_id": "left", "implementation": "branch.left", "write_keys": ["items"]},
                {"branch_id": "right", "implementation": "branch.right", "write_keys": ["items"]},
            ],
        },
        write_keys=["items"],
        buffer=buffer,
    )

    assert outcome.status == StepStatus.SUCCEEDED
    assert buffer.read("items") == ["right"]


def test_parallel_group_fail_fast_fails_on_first_branch_error() -> None:
    functions = FunctionStepRegistry()
    functions.register("branch.good", lambda buffer: {"items": ["ok"]})
    functions.register("branch.bad", lambda buffer: (_ for _ in ()).throw(RuntimeError("boom")))

    outcome = _run_parallel(
        _runner(functions),
        metadata={
            "failure_strategy": "fail_fast",
            "branches": [
                {"branch_id": "good", "implementation": "branch.good", "write_keys": ["items"]},
                {"branch_id": "bad", "implementation": "branch.bad", "write_keys": ["items"]},
            ],
        },
    )

    assert outcome.status == StepStatus.FAILED
    assert "boom" in outcome.error_message


def test_parallel_group_best_effort_allows_partial_failure() -> None:
    functions = FunctionStepRegistry()
    functions.register("branch.good", lambda buffer: {"items": ["ok"]})
    functions.register("branch.bad", lambda buffer: (_ for _ in ()).throw(RuntimeError("boom")))
    buffer = DataBuffer()

    outcome = _run_parallel(
        _runner(functions),
        metadata={
            "failure_strategy": "best_effort",
            "summary_key": "summary",
            "branches": [
                {"branch_id": "good", "implementation": "branch.good", "write_keys": ["items"]},
                {"branch_id": "bad", "implementation": "branch.bad", "write_keys": ["items"]},
            ],
        },
        write_keys=[
            "items",
            "branch_results",
            "failed_branch_results",
            "success_count",
            "failure_count",
            "partial_success",
            "summary",
        ],
        buffer=buffer,
    )

    assert outcome.status == StepStatus.SUCCEEDED
    assert outcome.next_hint == "best_effort"
    assert outcome.metrics["success_count"] == 1
    assert outcome.metrics["failure_count"] == 1
    assert outcome.metrics["partial_success"] is True
    assert buffer.read("success_count") == 1
    assert buffer.read("failure_count") == 1
    assert buffer.read("partial_success") is True
    assert buffer.read("summary")["partial_success"] is True
    assert [result["branch_id"] for result in buffer.read("branch_results")] == ["good"]
    failed = buffer.read("failed_branch_results")
    assert failed[0]["branch_id"] == "bad"
    assert failed[0]["error_type"] == "RuntimeError"


def test_parallel_group_all_success_fails_if_any_branch_fails() -> None:
    functions = FunctionStepRegistry()
    functions.register("branch.good", lambda buffer: {"items": ["ok"]})
    functions.register("branch.bad", lambda buffer: (_ for _ in ()).throw(RuntimeError("boom")))

    outcome = _run_parallel(
        _runner(functions),
        metadata={
            "failure_strategy": "all_success",
            "branches": [
                {"branch_id": "good", "implementation": "branch.good", "write_keys": ["items"]},
                {"branch_id": "bad", "implementation": "branch.bad", "write_keys": ["items"]},
            ],
        },
    )

    assert outcome.status == StepStatus.FAILED
    assert "boom" in outcome.error_message


def test_parallel_group_min_success_passes_when_threshold_met() -> None:
    functions = FunctionStepRegistry()
    functions.register("branch.good", lambda buffer: {"items": ["ok"]})
    functions.register("branch.bad", lambda buffer: (_ for _ in ()).throw(RuntimeError("boom")))
    buffer = DataBuffer()

    outcome = _run_parallel(
        _runner(functions),
        metadata={
            "failure_strategy": "min_success",
            "min_success": 1,
            "branch_results_key": "branch_results",
            "branches": [
                {"branch_id": "good", "implementation": "branch.good", "write_keys": ["items"]},
                {"branch_id": "bad", "implementation": "branch.bad", "write_keys": ["items"]},
            ],
        },
        write_keys=["items", "branch_results"],
        buffer=buffer,
    )

    assert outcome.status == StepStatus.SUCCEEDED
    assert buffer.read("items") == ["ok"]
    assert outcome.metrics["success_count"] == 1
    assert outcome.metrics["failure_count"] == 1
    assert outcome.metrics["min_success"] == 1
