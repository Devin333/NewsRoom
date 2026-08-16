from __future__ import annotations

import json

import pytest

from framework.harness import (
    HarnessControlPlane,
    HarnessGraphDecisionType,
    HarnessGraphTerminalFailureRecord,
    HarnessRetryPolicy,
    HarnessRunSpec,
    HarnessStepSpec,
    HarnessValidationError,
    HarnessWorkerResult,
    InMemoryHarnessEventPort,
)
from framework.harness.workflow.spec import HarnessWorkflowSpec


def test_terminal_failure_record_binds_adjacent_durable_decision_projection() -> None:
    port, decision_commit, projection_commit = _failed_run_commits()

    record = HarnessGraphTerminalFailureRecord.from_commits(
        decision_commit,
        projection_commit,
    )
    restored = HarnessGraphTerminalFailureRecord.from_dict(
        json.loads(json.dumps(record.to_dict()))
    )

    assert restored == record
    assert record.run_id == "run-terminal-failure-record"
    assert record.terminal_reason_code == "graph_terminal_failure"
    assert record.terminal_decision_ref == (
        decision_commit.decision.decision_checksum
    )
    assert record.terminal_projection_ref == (
        projection_commit.state.projection_checksum
    )
    assert record.terminal_projection_sequence == (
        record.terminal_decision_sequence + 1
    )
    assert record.failed_node_refs == decision_commit.decision.evidence_refs
    assert record.failed_nodes[0].status.value == "failed"
    assert record.record_checksum is not None
    assert port.recover_graph(record.run_id).state == projection_commit.state


def test_terminal_failure_record_rejects_noncausal_projection() -> None:
    _port, decision_commit, projection_commit = _failed_run_commits()
    # Passing a preceding real projection exercises the record's causal check.
    preceding = next(
        item
        for item in _port.recover_graph("run-terminal-failure-record").projection_commits
        if item.sequence < projection_commit.sequence
    )

    with pytest.raises(HarnessValidationError) as captured:
        HarnessGraphTerminalFailureRecord.from_commits(
            decision_commit,
            preceding,
        )

    assert captured.value.code == "graph_terminal_failure_projection_mismatch"


def test_terminal_failure_record_rejects_tampered_sequence_and_checksum() -> None:
    _port, decision_commit, projection_commit = _failed_run_commits()
    record = HarnessGraphTerminalFailureRecord.from_commits(
        decision_commit,
        projection_commit,
    )
    sequence_tamper = record.to_dict()
    sequence_tamper["terminal_projection_sequence"] += 1

    with pytest.raises(HarnessValidationError) as sequence_error:
        HarnessGraphTerminalFailureRecord.from_dict(sequence_tamper)

    assert sequence_error.value.code == "graph_terminal_failure_sequence_mismatch"

    checksum_tamper = record.to_dict()
    checksum_tamper["terminal_reason_code"] = "forged_failure"
    with pytest.raises(HarnessValidationError) as checksum_error:
        HarnessGraphTerminalFailureRecord.from_dict(checksum_tamper)

    assert checksum_error.value.code == (
        "graph_terminal_failure_record_checksum_mismatch"
    )


def _failed_run_commits():
    run_id = "run-terminal-failure-record"
    port = InMemoryHarnessEventPort()
    workflow = HarnessWorkflowSpec(
        workflow_id="terminal-failure-record",
        steps=(
            HarnessStepSpec(
                step_id="collect",
                worker_type="llm",
                retry_policy=HarnessRetryPolicy(
                    max_attempts=2,
                    retry_on_statuses=("failed",),
                ),
            ),
        ),
        entry_step_id="collect",
    )
    HarnessControlPlane(
        event_port=port,
        worker_registry={
            "collect": (
                HarnessWorkerResult(status="failed", error="first"),
                HarnessWorkerResult(status="failed", error="second"),
            )
        },
    ).run(HarnessRunSpec(run_id=run_id, workflow=workflow))
    recovery = port.recover_graph(run_id)
    decision_commit = next(
        item
        for item in recovery.decision_commits
        if item.decision.decision_type is HarnessGraphDecisionType.COMPLETE_RUN
        and item.decision.reason_code == "graph_terminal_failure"
    )
    projection_commit = next(
        item
        for item in recovery.projection_commits
        if item.cause_checksum == decision_commit.decision.decision_checksum
    )
    return port, decision_commit, projection_commit
