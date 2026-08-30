from __future__ import annotations

from backend.research.domain.common import GateResult
from backend.research.domain.reader_repair import ReaderRepairCase
from backend.research.reader_repair.repair_gates import ReaderRepairGateSuite


class ReaderRepairGate(ReaderRepairGateSuite):
    def verify_case(self, repair_case: ReaderRepairCase) -> list[GateResult]:
        return super().verify_case(repair_case)


__all__ = ["ReaderRepairGate"]
