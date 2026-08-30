from __future__ import annotations

from backend.research.domain import ReaderIssue
from backend.research.reader_repair import InMemoryReaderRepairMemory, ReaderRepairMemoryService
from tests.backend.research.reader_repair._fixtures import make_repair_case


def test_successful_and_failed_repairs_commit_episodic_memory() -> None:
    memory = InMemoryReaderRepairMemory()
    service = ReaderRepairMemoryService(memory)
    issue = ReaderIssue(
        issue_id="issue-table",
        paper_id="paper-1",
        issue_type="table_parse_error",
        error_signature="table-sig",
        symptom="Table parse failed.",
        source_refs=["paper://paper-1/table-1"],
        payload_ref="payload-before",
    )
    success = make_repair_case("case-success", issue=issue, successful=True)
    failed = make_repair_case("case-failed", issue=issue, successful=False)

    success_ref = service.commit_case(success)
    failed_ref = service.commit_case(failed)

    assert success_ref.endswith("/case/case-success")
    assert failed_ref.endswith("/case/case-failed")
    assert set(memory.cases) == {"case-success", "case-failed"}
    assert all(candidate.namespace == "research.reader_repair" for candidate in memory.write_candidates.values())
