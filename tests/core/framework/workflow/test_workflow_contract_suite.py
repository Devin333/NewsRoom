from __future__ import annotations

from pathlib import Path

from core.framework.specs import WorkflowStatus

from helpers import (
    make_linear_workflow,
    read_events,
    read_manifest,
    run_dir,
    run_workflow,
)


CONTRACT_GROUPS: dict[str, tuple[str, ...]] = {
    "C01": ("test_workflow_compiler_*.py", "test_compiler_*_contract.py"),
    "C02": ("test_data_buffer_*.py", "test_buffer.py"),
    "C03": ("test_routing*.py",),
    "C04": ("test_scheduler_*.py",),
    "C05": ("test_retry_timeout_failure.py", "test_executor.py"),
    "C06": ("test_checkpoint_*.py",),
    "C07": ("test_artifact_publishers.py", "test_manifest_contract.py"),
    "C08": ("test_event_ordering_contract.py",),
    "C09": ("test_step_runner*.py", "test_target_step_runners.py"),
    "C10": ("test_human_review_*.py",),
    "C11": (
        "test_parallel_*.py",
        "test_parallel_join_subworkflow.py",
        "test_join_contract.py",
        "test_subworkflow*.py",
    ),
    "C12": ("test_run_operations_*.py",),
    "C13": (
        "test_diagnostics_replay.py",
        "test_run_diagnostics.py",
        "test_run_replay_bundle.py",
        "test_run_compare.py",
        "test_run_health_report.py",
    ),
    "C14": (
        "test_resource_policy.py",
        "test_global_budget_policy.py",
        "test_budget_*.py",
        "test_runtime_safety_policy.py",
    ),
}


def test_workflow_contract_readme_lists_all_contract_groups() -> None:
    readme = Path(__file__).with_name("README.md").read_text(encoding="utf-8")

    for group_id in CONTRACT_GROUPS:
        assert group_id in readme


def test_each_workflow_contract_group_has_at_least_one_test_file() -> None:
    test_dir = Path(__file__).parent

    missing = [
        group_id
        for group_id, patterns in CONTRACT_GROUPS.items()
        if not any(test_dir.glob(pattern) for pattern in patterns)
    ]

    assert missing == []


def test_workflow_helpers_build_and_run_isolated_linear_workflow(tmp_path) -> None:
    workflow = make_linear_workflow(["plan", "write"])

    result = run_workflow(tmp_path, workflow, run_id="contract-helper-run")

    directory = run_dir(tmp_path, "contract-helper-run")
    manifest = read_manifest(directory)
    events = read_events(directory)
    assert result.status == WorkflowStatus.SUCCEEDED
    assert result.path == ["plan", "write"]
    assert manifest["status"] == "succeeded"
    assert [event["event_type"] for event in events] == [
        "workflow_started",
        "step_started",
        "step_succeeded",
        "edge_evaluated",
        "edge_traversed",
        "step_started",
        "step_succeeded",
        "workflow_succeeded",
    ]
