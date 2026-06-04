from __future__ import annotations

import pytest

from framework.harness import (
    ContextEnvelope,
    FakeSubAgentRuntime,
    FakeSubAgentWorker,
    HarnessValidationError,
    HarnessWorkerResult,
    fake_subagent_spec,
)


def test_fake_subagent_runtime_outputs_legal_payload() -> None:
    runtime = FakeSubAgentRuntime(fake_subagent_spec())
    result = runtime.invoke(runtime.build_invocation())

    assert result.output == {"result": "ok"}
    assert result.errors == ()


def test_subagent_result_rejects_illegal_flow_output_from_worker() -> None:
    with pytest.raises(HarnessValidationError):
        HarnessWorkerResult(status="succeeded", output={"result": "ok", "next_step": "publish"})


def test_fake_subagent_runtime_can_simulate_sibling_private_context_attempt() -> None:
    with pytest.raises(HarnessValidationError):
        runtime = FakeSubAgentRuntime(fake_subagent_spec())
        runtime.build_invocation(
            context=ContextEnvelope(
                envelope_id="context://unsafe",
                dynamic_tail={"sibling_private_notes": ["private"]},
            )
        )
