from __future__ import annotations

from pathlib import Path

from core.framework.workflow import (
    inspect_workflow_run_diagnostics,
    build_workflow_replay_bundle,
)

from helpers import make_linear_workflow, run_workflow


def test_diagnostics_replay_contract_builds_diagnostics_and_replay_bundle(tmp_path) -> None:
    workflow = make_linear_workflow(["plan", "write"])
    result = run_workflow(tmp_path, workflow, run_id="diagnostics-replay-contract")

    run_directory = tmp_path / result.run_id
    diagnostics = inspect_workflow_run_diagnostics(run_directory)
    replay_bundle = build_workflow_replay_bundle(run_directory)

    assert diagnostics.status == "succeeded"
    assert diagnostics.healthy is True
    assert diagnostics.resume_available is False
    assert replay_bundle.manifest["run_id"] == result.run_id
    assert replay_bundle.manifest["status"] == "succeeded"
    assert replay_bundle.events
    assert replay_bundle.step_results


def test_diagnostics_replay_contract_files_are_present() -> None:
    test_dir = Path(__file__).parent

    expected_files = [
        "test_run_diagnostics.py",
        "test_run_replay_bundle.py",
        "test_run_compare.py",
        "test_run_health_report.py",
    ]

    assert [name for name in expected_files if not (test_dir / name).exists()] == []
