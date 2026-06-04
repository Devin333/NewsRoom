from __future__ import annotations

from business.research.domain.common import GateResult
from business.research.domain.reader_repair import ReaderRepairCase


class ReaderRepairGate:
    def verify_case(self, repair_case: ReaderRepairCase) -> list[GateResult]:
        results: list[GateResult] = []
        if repair_case.successful and not repair_case.payload_after_ref:
            results.append(GateResult.fail("ReaderRepairPayloadFidelityGate", "successful repair requires payload_after_ref"))
        else:
            results.append(GateResult.pass_("ReaderRepairPayloadFidelityGate"))
        if repair_case.metadata.get("active_skill_mutation"):
            results.append(GateResult.fail("ReaderRepairSkillMutationGate", "ordinary reader repair must not mutate active skills"))
        else:
            results.append(GateResult.pass_("ReaderRepairSkillMutationGate"))
        return results


__all__ = ["ReaderRepairGate"]
