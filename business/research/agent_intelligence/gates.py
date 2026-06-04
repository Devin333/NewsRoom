from __future__ import annotations

from business.research.agent_intelligence.models import AgentSkillToolIntelligence, is_registered_agent_task
from business.research.domain.common import GateResult


def validate_agent_intelligence(intelligence: AgentSkillToolIntelligence) -> list[GateResult]:
    results: list[GateResult] = []
    if not is_registered_agent_task(intelligence.task_type):
        results.append(GateResult.fail("AgentTaskRegistryGate", "agent task type is outside the registry"))
    else:
        results.append(GateResult.pass_("AgentTaskRegistryGate"))
    if not intelligence.evidence_refs:
        results.append(GateResult.fail("AgentIntelligenceEvidenceGate", "agent intelligence requires evidence refs"))
    else:
        results.append(GateResult.pass_("AgentIntelligenceEvidenceGate"))
    if intelligence.mutates_active_skill:
        results.append(GateResult.fail("AgentSkillMutationGate", "Research intelligence must not mutate active skills"))
    else:
        results.append(GateResult.pass_("AgentSkillMutationGate"))
    return results


__all__ = ["validate_agent_intelligence"]
