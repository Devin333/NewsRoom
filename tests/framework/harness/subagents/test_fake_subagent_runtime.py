from __future__ import annotations

from dataclasses import replace

import pytest

from framework.harness import (
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
    runtime = FakeSubAgentRuntime(fake_subagent_spec())
    with pytest.raises(HarnessValidationError):
        replace(
            runtime.build_invocation(),
            schema_version="newsroom.subagent-invocation/v2",
        )
