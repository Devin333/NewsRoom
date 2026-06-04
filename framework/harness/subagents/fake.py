from __future__ import annotations

from framework.harness.context.models import ContextEnvelope
from framework.harness.control_plane.policy import HarnessBudget, HarnessBudgetSnapshot
from framework.harness.subagents.context import SubAgentContextBuilder
from framework.harness.subagents.gates import FakeSubAgentGateSuite
from framework.harness.subagents.models import SubAgentInvocation, SubAgentSpec
from framework.harness.subagents.runtime import SubAgentRuntime
from framework.harness.subagents.transcript import FakeSubAgentTranscriptStore
from framework.harness.workers.fake import FakeSubAgentWorker
from framework.harness.workers.result import HarnessWorkerResult


class FakeSubAgentContextBuilder(SubAgentContextBuilder):
    pass


class FakeSubAgentRuntime(SubAgentRuntime):
    def __init__(self, spec: SubAgentSpec, worker: FakeSubAgentWorker | None = None) -> None:
        super().__init__(
            workers={spec.subagent_id: worker or FakeSubAgentWorker((HarnessWorkerResult(status="succeeded", output={"result": "ok"}),))},
            transcript_store=FakeSubAgentTranscriptStore(),
            gates=FakeSubAgentGateSuite(),
        )
        self.spec = spec
        self._invocation_count = 0

    def build_invocation(
        self,
        *,
        parent_run_id: str = "parent-run",
        workflow_id: str = "workflow",
        step_id: str = "step",
        context: ContextEnvelope | None = None,
        input_refs: tuple[str, ...] = ("input://1",),
    ) -> SubAgentInvocation:
        budget = HarnessBudget.safe_default()
        snapshot = HarnessBudgetSnapshot.from_budget(budget)
        self._invocation_count += 1
        child_run_id = f"{parent_run_id}:{self.spec.subagent_id}:{self._invocation_count}"
        envelope = FakeSubAgentContextBuilder().build(
            parent_run_id=parent_run_id,
            child_run_id=child_run_id,
            spec=self.spec,
            context_pack=context or ContextEnvelope(envelope_id="context://subagent", token_estimate=10),
            input_refs=input_refs,
            memory_context_refs=tuple(f"memory://{namespace}" for namespace in self.spec.allowed_memory_namespaces),
            budget_snapshot=snapshot,
        )
        return SubAgentInvocation(
            invocation_id=f"invocation://{child_run_id}",
            parent_run_id=parent_run_id,
            child_run_id=child_run_id,
            workflow_id=workflow_id,
            step_id=step_id,
            subagent_spec=self.spec,
            input_refs=input_refs,
            context_envelope=envelope,
            budget_snapshot=snapshot,
            metadata={"input_refs": list(input_refs)},
        )


def fake_subagent_spec(**overrides) -> SubAgentSpec:
    values = {
        "subagent_id": "critic",
        "role": "critic",
        "purpose": "Review structured candidates.",
        "input_schema": {"required": ["input_refs"]},
        "output_schema": {"required": ["result"], "properties": {"result": {"type": "string"}}},
        "allowed_tools": ("search.read",),
        "allowed_memory_namespaces": ("research.public",),
        "context_policy": {"allow_sibling_history": False},
        "budget": {"max_turns": 2, "max_tool_calls": 1, "max_memory_ops": 1},
    }
    values.update(overrides)
    return SubAgentSpec(**values)


__all__ = ["FakeSubAgentContextBuilder", "FakeSubAgentRuntime", "FakeSubAgentWorker", "fake_subagent_spec"]
