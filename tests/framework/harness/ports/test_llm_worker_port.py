from __future__ import annotations

from framework.harness import (
    FakeLLMWorker,
    HarnessControlPlane,
    InMemoryHarnessEventPort,
    HarnessRunSpec,
    HarnessRunStatus,
    HarnessStepSpec,
    HarnessWorkerResult,
    HarnessWorkflowSpec,
)


def test_fake_llm_worker_can_be_called_by_harness_control_plane() -> None:
    worker = FakeLLMWorker(
        responses=(HarnessWorkerResult(status="succeeded", output={"candidate": {"summary": "ok"}}),)
    )
    workflow = HarnessWorkflowSpec(
        workflow_id="llm-port",
        steps=(HarnessStepSpec(step_id="draft", worker_type="llm", output_key="draft"),),
        entry_step_id="draft",
    )

    result = HarnessControlPlane(
        event_port=InMemoryHarnessEventPort(),
        worker_registry={"draft": worker},
    ).run(
        HarnessRunSpec(run_id="run-llm-port", workflow=workflow)
    )

    assert result.state.status == HarnessRunStatus.SUCCEEDED
    assert worker.requests[0]["step_id"] == "draft"
    assert result.worker_results["draft"].output == {"candidate": {"summary": "ok"}}
