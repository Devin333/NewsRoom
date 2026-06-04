from __future__ import annotations

from business.research.domain import ReaderIssue
from business.research.reader_repair import InMemoryReaderRepairMemory, ReaderRepairMemoryService
from tests.business.research.reader_repair._fixtures import make_repair_case


def test_repair_memory_query_recalls_successful_and_failed_cases() -> None:
    memory = InMemoryReaderRepairMemory()
    service = ReaderRepairMemoryService(memory)
    issue = ReaderIssue(
        issue_id="issue-table",
        paper_id="paper-1",
        issue_type="table_parse_error",
        error_signature="table_parse_error:build_reader_payload:pdf:missing_cells",
        symptom="Table dropped cells.",
        source_refs=["paper://paper-1/table-1"],
        payload_ref="reader-payload-1",
    )
    success = make_repair_case("case-success", issue=issue, successful=True)
    failed = make_repair_case("case-failed", issue=issue, successful=False)
    memory.write_case(success)
    memory.write_case(failed)

    recalled = service.recall(service.build_query(issue, source_format="pdf"))

    assert [case.repair_case_id for case in recalled["similar_successful_cases"]] == ["case-success"]
    assert [case.repair_case_id for case in recalled["similar_failed_cases"]] == ["case-failed"]


def test_repair_memory_query_rejects_unauthorized_namespace() -> None:
    issue = ReaderIssue(
        issue_id="issue-schema",
        paper_id="paper-1",
        issue_type="reader_payload_schema_error",
        error_signature="schema",
        symptom="Payload is malformed.",
    )
    query = ReaderRepairMemoryService(InMemoryReaderRepairMemory()).build_query(issue)

    assert query.namespace == "research.reader_repair"
