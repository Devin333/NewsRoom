from __future__ import annotations

from framework.harness.context.models import ContextEnvelope
from framework.harness.control_plane.policy import HarnessBudgetSnapshot
from framework.harness.subagents.models import SubAgentContextEnvelope, SubAgentSpec
from framework.harness.subagents.policy import SubAgentToolPolicy


class SubAgentContextBuilder:
    def build(
        self,
        *,
        parent_run_id: str,
        child_run_id: str,
        spec: SubAgentSpec,
        context_pack: ContextEnvelope,
        input_refs: tuple[str, ...],
        memory_context_refs: tuple[str, ...],
        budget_snapshot: HarnessBudgetSnapshot,
    ) -> SubAgentContextEnvelope:
        tool_policy = SubAgentToolPolicy(
            subagent_id=spec.subagent_id,
            allowed_tools=spec.allowed_tools,
            policy_ref=f"tool-policy://{child_run_id}",
        )
        return SubAgentContextEnvelope(
            child_run_id=child_run_id,
            parent_run_id=parent_run_id,
            subagent_id=spec.subagent_id,
            role=spec.role,
            allowed_input_refs=input_refs,
            context_pack=context_pack,
            memory_context_refs=memory_context_refs,
            tool_policy_ref=tool_policy.policy_ref,
            budget_snapshot=budget_snapshot,
            redaction_report={"removed_private_fields": []},
        )


__all__ = ["SubAgentContextBuilder"]
