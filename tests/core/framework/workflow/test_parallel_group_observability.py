from __future__ import annotations

import time

from core.framework.artifacts import ArtifactManager
from core.framework.specs import ArtifactPolicySpec, StepSpec, StepStatus, StepType
from core.framework.workflow import DataBuffer, FunctionStepRegistry, ParallelGroupStepRunner


def _parallel_step(*, metadata: dict, write_keys: list[str] | None = None) -> StepSpec:
    return StepSpec(
        "parallel",
        "parallel.observed",
        step_type=StepType.PARALLEL_GROUP,
        write_keys=write_keys or ["items", "branch_results", "failed_branch_results"],
        metadata=metadata,
    )


def test_parallel_group_records_branch_metrics() -> None:
    functions = FunctionStepRegistry()
    functions.register("branch.good", lambda buffer: {"items": ["ok"]})
    buffer = DataBuffer()

    outcome = ParallelGroupStepRunner(functions).run(
        _parallel_step(
            metadata={
                "branch_results_key": "branch_results",
                "branches": [
                    {"branch_id": "good", "implementation": "branch.good", "write_keys": ["items"]}
                ],
            },
            write_keys=["items", "branch_results"],
        ),
        buffer.scope(read_keys=[], write_keys=["items", "branch_results"]),
    )

    assert outcome.status == StepStatus.SUCCEEDED
    branch_result = buffer.read("branch_results")[0]
    assert branch_result["attempts"] == 1
    assert branch_result["duration_ms"] >= 0
    assert branch_result["started_at"]
    assert branch_result["finished_at"]
    assert branch_result["error_type"] is None
    assert branch_result["artifact_refs"] == []


def test_parallel_branch_retry_succeeds_after_transient_failure() -> None:
    functions = FunctionStepRegistry()
    attempts = {"count": 0}

    def flaky(buffer):
        attempts["count"] += 1
        if attempts["count"] == 1:
            raise RuntimeError("transient")
        return {"items": ["ok"]}

    functions.register("branch.flaky", flaky)
    buffer = DataBuffer()

    outcome = ParallelGroupStepRunner(functions).run(
        _parallel_step(
            metadata={
                "branch_results_key": "branch_results",
                "branches": [
                    {
                        "branch_id": "flaky",
                        "implementation": "branch.flaky",
                        "write_keys": ["items"],
                        "retry_policy": {
                            "max_retries": 2,
                            "retry_delay_seconds": [0],
                            "retry_on_error_types": ["RuntimeError"],
                        },
                    }
                ],
            },
            write_keys=["items", "branch_results"],
        ),
        buffer.scope(read_keys=[], write_keys=["items", "branch_results"]),
    )

    assert outcome.status == StepStatus.SUCCEEDED
    assert attempts["count"] == 2
    assert buffer.read("branch_results")[0]["attempts"] == 2


def test_parallel_branch_retry_exhausted_records_attempts() -> None:
    functions = FunctionStepRegistry()
    functions.register("branch.bad", lambda buffer: (_ for _ in ()).throw(RuntimeError("nope")))
    buffer = DataBuffer()

    outcome = ParallelGroupStepRunner(functions).run(
        _parallel_step(
            metadata={
                "failure_strategy": "best_effort",
                "branches": [
                    {
                        "branch_id": "bad",
                        "implementation": "branch.bad",
                        "write_keys": ["items"],
                        "retry_policy": {
                            "max_retries": 2,
                            "retry_delay_seconds": [0, 0],
                            "retry_on_error_types": ["RuntimeError"],
                        },
                    }
                ],
            },
        ),
        buffer.scope(read_keys=[], write_keys=["items", "branch_results", "failed_branch_results"]),
    )

    assert outcome.status == StepStatus.SUCCEEDED
    failed = buffer.read("failed_branch_results")[0]
    assert failed["branch_id"] == "bad"
    assert failed["attempts"] == 3
    assert failed["error_type"] == "RuntimeError"


def test_parallel_branch_timeout_records_failed_branch() -> None:
    functions = FunctionStepRegistry()
    functions.register("branch.slow", lambda buffer: (time.sleep(0.05), {"items": ["late"]})[1])
    buffer = DataBuffer()

    outcome = ParallelGroupStepRunner(functions, max_workers=1).run(
        _parallel_step(
            metadata={
                "failure_strategy": "best_effort",
                "branches": [
                    {
                        "branch_id": "slow",
                        "implementation": "branch.slow",
                        "write_keys": ["items"],
                        "timeout_seconds": 0.001,
                    }
                ],
            },
        ),
        buffer.scope(read_keys=[], write_keys=["items", "branch_results", "failed_branch_results"]),
    )

    assert outcome.status == StepStatus.SUCCEEDED
    failed = buffer.read("failed_branch_results")[0]
    assert failed["branch_id"] == "slow"
    assert failed["error_type"] == "TimeoutError"
    assert failed["attempts"] == 1


def test_parallel_group_records_branch_lineage() -> None:
    functions = FunctionStepRegistry()
    functions.register("branch.good", lambda buffer: {"items": ["ok"]})

    outcome = ParallelGroupStepRunner(functions).run(
        _parallel_step(
            metadata={
                "branches": [
                    {"branch_id": "good", "implementation": "branch.good", "write_keys": ["items"]}
                ],
            },
            write_keys=["items"],
        ),
        DataBuffer().scope(read_keys=[], write_keys=["items"]),
    )

    assert outcome.status == StepStatus.SUCCEEDED
    assert outcome.lineage == [
        {"step_id": "parallel", "branch_id": "good", "output_keys": ["items"]}
    ]


def test_parallel_group_writes_branch_artifacts_when_enabled(tmp_path) -> None:
    functions = FunctionStepRegistry()
    functions.register("branch.good", lambda buffer: {"items": ["ok"]})
    artifact_manager = ArtifactManager(tmp_path)
    artifact_manager.start_run("run-parallel")
    runner = ParallelGroupStepRunner(
        functions,
        artifact_manager=artifact_manager,
        run_id="run-parallel",
    )
    buffer = DataBuffer()

    outcome = runner.run(
        StepSpec(
            "parallel",
            "parallel.observed",
            step_type=StepType.PARALLEL_GROUP,
            write_keys=["items", "branch_results"],
            artifact_policy=ArtifactPolicySpec(artifact_types=["parallel_branch"]),
            metadata={
                "branch_results_key": "branch_results",
                "branches": [
                    {"branch_id": "good", "implementation": "branch.good", "write_keys": ["items"]}
                ],
            },
        ),
        buffer.scope(read_keys=[], write_keys=["items", "branch_results"]),
    )

    assert outcome.status == StepStatus.SUCCEEDED
    assert len(outcome.artifacts) == 1
    artifact_ref = outcome.artifacts[0]
    assert artifact_ref.artifact_id == "parallel:parallel:good"
    assert artifact_ref.path == "parallel/parallel/good.json"
    assert (tmp_path / "run-parallel" / "parallel" / "parallel" / "good.json").exists()
    branch_result = buffer.read("branch_results")[0]
    assert branch_result["artifact_refs"][0]["artifact_id"] == "parallel:parallel:good"
