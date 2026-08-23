from __future__ import annotations

from framework.events.canonical import checksum_for
from framework.harness.context.models import (
    CONTEXT_GRAPH_TASK_PLAN_STAGE_IDENTITY_SCHEMA_V2,
    ContextEnvelope,
    ContextGraphIdentity,
    ContextTaskExecutionIdentity,
)
from framework.harness.control_plane.policy import HarnessBudget, HarnessBudgetSnapshot
from framework.harness.graph.versioning import (
    GRAPH_ONLY_NORMALIZED_HARNESS_GRAPH_SCHEMA,
    HARNESS_CONDITION_POLICY_VERSION,
    HARNESS_GRAPH_ONLY_COMPILER_VERSION,
)
from framework.harness.subagents.context import SubAgentContextBuilder
from framework.harness.subagents.gates import FakeSubAgentGateSuite
from framework.harness.subagents.models import (
    SUBAGENT_INVOCATION_SCHEMA_V3,
    SubAgentInvocation,
    SubAgentSpec,
)
from framework.harness.subagents.runtime import SubAgentRuntime
from framework.harness.subagents.transcript import (
    SUBAGENT_ATTEMPT_IDENTITY_SCHEMA_V3,
    FakeSubAgentTranscriptStore,
    SubAgentAttemptIdentity,
)
from framework.shared.time import utc_now
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
        step_id: str = "step",
        context: ContextEnvelope | None = None,
        input_refs: tuple[str, ...] = ("input://1",),
    ) -> SubAgentInvocation:
        budget = HarnessBudget.safe_default()
        snapshot = HarnessBudgetSnapshot.from_budget(budget)
        self._invocation_count += 1
        child_run_id = f"{parent_run_id}:{self.spec.subagent_id}:{self._invocation_count}"
        task_instance_id = f"test-instance-{self._invocation_count}"
        graph_checksum = checksum_for({"graph_id": "test-graph", "version": "1"})
        stage_binding_checksum = checksum_for({"stage_id": step_id})
        stage_identity_checksum = checksum_for(
            {
                "schema_version": CONTEXT_GRAPH_TASK_PLAN_STAGE_IDENTITY_SCHEMA_V2,
                "run_id": parent_run_id,
                "graph_schema_version": GRAPH_ONLY_NORMALIZED_HARNESS_GRAPH_SCHEMA,
                "compiler_version": HARNESS_GRAPH_ONLY_COMPILER_VERSION,
                "condition_policy_version": HARNESS_CONDITION_POLICY_VERSION,
                "graph_id": "test-graph",
                "graph_version": "1",
                "graph_checksum": graph_checksum,
                "stage_id": step_id,
                "stage_binding_checksum": stage_binding_checksum,
                "graph_ref": "test-graph@1",
            }
        )
        graph_identity = ContextGraphIdentity(
            run_id=parent_run_id,
            graph_id="test-graph",
            graph_version="1",
            graph_ref="test-graph@1",
            graph_schema_version=GRAPH_ONLY_NORMALIZED_HARNESS_GRAPH_SCHEMA,
            compiler_version=HARNESS_GRAPH_ONLY_COMPILER_VERSION,
            condition_policy_version=HARNESS_CONDITION_POLICY_VERSION,
            graph_checksum=graph_checksum,
            stage_id=step_id,
            stage_binding_checksum=stage_binding_checksum,
            stage_identity_schema=CONTEXT_GRAPH_TASK_PLAN_STAGE_IDENTITY_SCHEMA_V2,
            stage_identity_checksum=stage_identity_checksum,
            node_id=f"node-{step_id}",
            node_instance_id=f"node-instance-{self._invocation_count}",
            activity_id=f"activity-{self._invocation_count}",
            activity_attempt=1,
        )
        execution_identity = ContextTaskExecutionIdentity(
            plan_id="test-plan",
            plan_version=1,
            plan_checksum=checksum_for({"plan_id": "test-plan"}),
            task_id=self.spec.subagent_id,
            task_definition_checksum=checksum_for({"task_id": self.spec.subagent_id}),
            task_instance_id=task_instance_id,
            attempt=1,
        )
        generated_context = ContextEnvelope.for_graph(
            envelope_id=f"context://{child_run_id}",
            graph_identity=graph_identity,
            task_execution_identity=execution_identity,
            phase="EXECUTE",
            worker_id=self.spec.subagent_id,
            worker_type="subagent",
            token_estimate=10,
        )
        envelope = FakeSubAgentContextBuilder().build(
            parent_run_id=parent_run_id,
            child_run_id=child_run_id,
            spec=self.spec,
            context_pack=context or generated_context,
            input_refs=input_refs,
            memory_context_refs=(),
            budget_snapshot=snapshot,
        )
        attempt_identity = SubAgentAttemptIdentity(
            invocation_id=f"invocation://{child_run_id}",
            parent_run_id=parent_run_id,
            child_run_id=child_run_id,
            graph_id=graph_identity.graph_id,
            graph_version=graph_identity.graph_version,
            graph_ref=graph_identity.graph_ref,
            graph_schema_version=graph_identity.graph_schema_version,
            compiler_version=graph_identity.compiler_version,
            condition_policy_version=graph_identity.condition_policy_version,
            graph_checksum=graph_identity.graph_checksum,
            stage_id=graph_identity.stage_id,
            stage_binding_checksum=graph_identity.stage_binding_checksum,
            stage_identity_schema=graph_identity.stage_identity_schema,
            stage_identity_checksum=graph_identity.stage_identity_checksum,
            plan_id=execution_identity.plan_id,
            plan_version=execution_identity.plan_version,
            plan_checksum=execution_identity.plan_checksum,
            task_id=execution_identity.task_id,
            task_definition_checksum=execution_identity.task_definition_checksum,
            context_envelope_id=(context or generated_context).envelope_id,
            context_envelope_checksum=(context or generated_context).checksum,
            node_id=graph_identity.node_id,
            node_instance_id=graph_identity.node_instance_id,
            activity_id=graph_identity.activity_id,
            activity_attempt=graph_identity.activity_attempt,
            task_instance_id=execution_identity.task_instance_id,
            attempt=execution_identity.attempt,
            subagent_id=self.spec.subagent_id,
            schema_version=SUBAGENT_ATTEMPT_IDENTITY_SCHEMA_V3,
        )
        return SubAgentInvocation(
            invocation_id=f"invocation://{child_run_id}",
            parent_run_id=parent_run_id,
            child_run_id=child_run_id,
            stage_id=step_id,
            task_id=self.spec.subagent_id,
            task_instance_id=task_instance_id,
            attempt=1,
            observed_at=utc_now(),
            subagent_spec=self.spec,
            input_refs=input_refs,
            context_envelope=envelope,
            budget_snapshot=snapshot,
            attempt_identity=attempt_identity,
            metadata={"input_refs": list(input_refs)},
            schema_version=SUBAGENT_INVOCATION_SCHEMA_V3,
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
