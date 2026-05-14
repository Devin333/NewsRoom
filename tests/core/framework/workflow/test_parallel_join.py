from core.framework.artifacts import ArtifactManager
from core.framework.specs import EdgeSpec, StepSpec, StepStatus, StepType, WorkflowSpec, WorkflowStatus
from core.framework.workflow import (
    DataBuffer,
    FunctionStepRegistry,
    FunctionStepRunner,
    JoinStepRunner,
    ParallelGroupStepRunner,
    StepRunnerRegistry,
    WorkflowExecutor,
)


def test_parallel_group_and_join_execute_pure_functions(tmp_path) -> None:
    functions = FunctionStepRegistry()
    functions.register("branch.left", lambda buffer: {"left": buffer.read("request")["topic"]})
    functions.register("branch.right", lambda buffer: {"right": "ok"})
    registry = StepRunnerRegistry.with_function_runner(FunctionStepRunner(functions))
    registry.register(StepType.PARALLEL_GROUP, ParallelGroupStepRunner(functions))
    registry.register(StepType.JOIN, JoinStepRunner())
    spec = WorkflowSpec(
        workflow_id="parallel-join",
        name="Parallel Join",
        version="1.0",
        start_step_id="parallel",
        steps=[
            StepSpec(
                "parallel",
                "parallel.sources",
                step_type=StepType.PARALLEL_GROUP,
                read_keys=["request"],
                write_keys=["left", "right", "branch_outputs", "branch_results"],
                required_output_keys=["left", "right", "branch_outputs", "branch_results"],
                metadata={
                    "namespace_key": "branch_outputs",
                    "branch_results_key": "branch_results",
                    "branches": [
                        {
                            "branch_id": "left",
                            "implementation": "branch.left",
                            "read_keys": ["request"],
                            "write_keys": ["left"],
                        },
                        {
                            "branch_id": "right",
                            "implementation": "branch.right",
                            "write_keys": ["right"],
                        },
                    ],
                },
            ),
            StepSpec(
                "join",
                "join.all",
                step_type=StepType.JOIN,
                read_keys=["left", "right", "branch_results"],
                write_keys=["join_result"],
                required_output_keys=["join_result"],
                metadata={"strategy": "all_success", "branch_results_key": "branch_results"},
            ),
        ],
        edges=[EdgeSpec("parallel-join", "parallel", "join")],
    )
    executor = WorkflowExecutor(
        function_step_runner=None,
        step_runner_registry=registry,
        artifact_manager=ArtifactManager(tmp_path),
    )

    result = executor.execute(spec, {"topic": "ai"}, profile="test", run_id="run-parallel-join")

    assert result.status == WorkflowStatus.SUCCEEDED
    assert result.output["branch_outputs"]["left"] == {"left": "ai"}
    assert result.output["join_result"]["strategy"] == "all_success"
    assert result.output["join_result"]["ready"] is True
    assert result.step_results["parallel"].metrics["branch_count"] == 2


def test_parallel_group_best_effort_allows_partial_failure(tmp_path) -> None:
    functions = FunctionStepRegistry()
    functions.register("branch.good", lambda buffer: {"items": ["ok"]})
    functions.register("branch.bad", lambda buffer: (_ for _ in ()).throw(RuntimeError("branch failed")))
    runner = ParallelGroupStepRunner(functions)
    buffer = DataBuffer()

    outcome = runner.run(
        StepSpec(
            "parallel",
            "parallel.sources",
            step_type=StepType.PARALLEL_GROUP,
            write_keys=["items", "branch_results", "summary"],
            required_output_keys=["items", "branch_results"],
            metadata={
                "failure_strategy": "best_effort",
                "branch_results_key": "branch_results",
                "summary_key": "summary",
                "branches": [
                    {"branch_id": "good", "implementation": "branch.good", "write_keys": ["items"]},
                    {"branch_id": "bad", "implementation": "branch.bad", "write_keys": ["items"]},
                ],
            },
        ),
        buffer.scope(read_keys=[], write_keys=["items", "branch_results", "summary"]),
    )

    assert outcome.status == StepStatus.SUCCEEDED
    assert outcome.next_hint == "best_effort"
    assert outcome.metrics["failed_branch_count"] == 1
    assert buffer.read("items") == ["ok"]
    assert buffer.read("summary")["failed_branch_count"] == 1


def test_parallel_write_conflict_is_validation_error() -> None:
    spec = WorkflowSpec(
        workflow_id="parallel-conflict",
        name="Parallel Conflict",
        version="1.0",
        start_step_id="parallel",
        steps=[
            StepSpec(
                "parallel",
                "parallel.sources",
                step_type=StepType.PARALLEL_GROUP,
                write_keys=["items"],
                metadata={
                    "branches": [
                        {"branch_id": "left", "implementation": "left", "write_keys": ["items"]},
                        {"branch_id": "right", "implementation": "right", "write_keys": ["items"]},
                    ]
                },
            )
        ],
    )

    result = spec.validation_result()

    assert "parallel_write_conflict" in {error.code for error in result.errors}
