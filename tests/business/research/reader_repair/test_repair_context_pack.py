from __future__ import annotations

from business.research.domain import ReaderIssue
from business.research.domain.reader_repair import ReaderRepairMemoryQuery, ReaderRepairRAGPolicy
from business.research.reader_repair import ReaderRepairContextBuilder, ReaderRepairGateSuite
from tests.business.research.reader_repair._fixtures import make_repair_case


def test_repair_context_pack_contains_success_failure_or_gap() -> None:
    issue = ReaderIssue(
        issue_id="issue-table",
        paper_id="paper-1",
        issue_type="table_parse_error",
        error_signature="table-sig",
        symptom="Table cells dropped.",
        source_refs=["paper://paper-1/table-1"],
        payload_ref="payload-before",
    )
    success = make_repair_case("case-success", issue=issue, successful=True)
    failed = make_repair_case("case-failed", issue=issue, successful=False)
    query = ReaderRepairMemoryQuery.from_issue(issue)

    pack = ReaderRepairContextBuilder().build_pack(
        issue=issue,
        query=query,
        successful_cases=[success],
        failed_cases=[failed],
        strategies=[],
        policy=ReaderRepairRAGPolicy(policy_id="repair-policy"),
    )

    assert pack.similar_successful_cases
    assert pack.similar_failed_cases
    assert all(result.passed for result in ReaderRepairGateSuite().verify_context_pack(pack))


def test_repair_context_pack_records_failure_case_gap_when_none_exist() -> None:
    issue = ReaderIssue(
        issue_id="issue-lineage",
        paper_id="paper-1",
        issue_type="source_lineage_missing",
        error_signature="lineage",
        symptom="Lineage is missing.",
        source_refs=["paper://paper-1/sec-1"],
    )
    query = ReaderRepairMemoryQuery.from_issue(issue)

    pack = ReaderRepairContextBuilder().build_pack(
        issue=issue,
        query=query,
        successful_cases=[],
        failed_cases=[],
        strategies=[],
    )

    assert pack.failure_case_gap_report == {"no_failed_cases_available": True}
