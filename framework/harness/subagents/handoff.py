from __future__ import annotations

from framework.harness.subagents.gates import SubAgentGateResult, SubAgentHandoffSchemaGate
from framework.harness.subagents.models import SubAgentHandoff


def verify_handoff(handoff: SubAgentHandoff) -> SubAgentGateResult:
    return SubAgentHandoffSchemaGate().evaluate(handoff)


__all__ = ["verify_handoff"]
