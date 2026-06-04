from __future__ import annotations

from framework.harness import FakeSubAgentRuntime, FakeSubAgentWorker, HarnessWorkerResult, SubAgentStatus, fake_subagent_spec


def test_subagent_runtime_invokes_worker_with_isolated_context() -> None:
    runtime = FakeSubAgentRuntime(fake_subagent_spec())
    invocation = runtime.build_invocation()

    result = runtime.invoke(invocation)

    assert result.status == SubAgentStatus.SUCCEEDED
    assert result.transcript_ref
    assert invocation.child_run_id != invocation.parent_run_id


def test_subagent_runtime_rejects_unauthorized_tool_call() -> None:
    worker = FakeSubAgentWorker(
        (HarnessWorkerResult(status="succeeded", output={"result": "ok", "requested_tools": ["artifact.write"]}),)
    )
    runtime = FakeSubAgentRuntime(fake_subagent_spec(allowed_tools=("search.read",)), worker)
    result = runtime.invoke(runtime.build_invocation())

    assert result.status == SubAgentStatus.HALTED
    gate_results = result.metadata["gate_results"]
    assert any(gate["gate"] == "subagent_tool_allowlist" and gate["passed"] is False for gate in gate_results)


def test_subagent_runtime_rejects_unauthorized_memory_namespace() -> None:
    worker = FakeSubAgentWorker(
        (HarnessWorkerResult(status="succeeded", output={"result": "ok", "memory_namespaces": ["research.private"]}),)
    )
    runtime = FakeSubAgentRuntime(fake_subagent_spec(allowed_memory_namespaces=("research.public",)), worker)
    result = runtime.invoke(runtime.build_invocation())

    assert result.status == SubAgentStatus.HALTED
    assert any(
        gate["gate"] == "subagent_memory_namespace" and gate["passed"] is False
        for gate in result.metadata["gate_results"]
    )


def test_subagent_runtime_halts_when_child_budget_exceeded() -> None:
    worker = FakeSubAgentWorker((HarnessWorkerResult(status="succeeded", output={"result": "ok", "turns_used": 3}),))
    runtime = FakeSubAgentRuntime(fake_subagent_spec(budget={"max_turns": 1, "max_tool_calls": 1, "max_memory_ops": 1}), worker)
    result = runtime.invoke(runtime.build_invocation())

    assert result.status == SubAgentStatus.HALTED
    assert any(gate["gate"] == "subagent_budget" and gate["passed"] is False for gate in result.metadata["gate_results"])
