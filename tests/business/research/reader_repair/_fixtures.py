from __future__ import annotations

from business.research.domain import ReaderIssue
from business.research.domain.reader_repair import ReaderRepairCase


def make_repair_case(case_id: str, *, issue: ReaderIssue, successful: bool) -> ReaderRepairCase:
    return ReaderRepairCase(
        repair_case_id=case_id,
        issue=issue,
        repair_strategy="Apply localized reader payload repair and verify source refs.",
        successful=successful,
        verification_results=[{"gate_name": "ReaderRepairPayloadFidelityGate", "passed": successful}],
        payload_before_ref=issue.payload_ref or "payload-before",
        payload_after_ref=f"{issue.payload_ref or 'payload'}:after" if successful else None,
        source_refs=issue.source_refs,
        failure_reason=None if successful else "localized patch did not preserve table structure",
        metadata={"strategy_steps": ["match issue signature", "patch target region", "verify source refs"]},
    )
