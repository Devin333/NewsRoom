from __future__ import annotations

from business.research.domain import SourceLineage
from business.research.domain.document import ResearchDocument, ResearchEquation, ResearchSection, ResearchTable
from business.research.reader import ReaderPayloadBuilder
from business.research.reader_repair import ReaderRepairIssueDetector
from tests.business.research.fakes import FakeResearchSourceProvider


def _payload_with_document(document: ResearchDocument):
    paper = FakeResearchSourceProvider().paper
    return ReaderPayloadBuilder().build(paper=paper, document=document)


def test_reader_payload_schema_issue_generates_stable_signature() -> None:
    document = ResearchDocument(
        paper_id="paper-harness-001",
        source_hash="sha256-empty",
        sections=[],
        lineage=SourceLineage(source_refs=["paper://paper-harness-001/raw"]),
    )
    payload = _payload_with_document(document)

    issues = ReaderRepairIssueDetector().detect(payload, run_id="repair-run-1")

    assert {issue.issue_type for issue in issues} >= {"section_boundary_error", "missing_required_section"}
    signatures = [issue.error_signature for issue in issues]
    assert signatures == [issue.error_signature for issue in ReaderRepairIssueDetector().detect(payload, run_id="repair-run-2")]


def test_table_and_formula_issues_have_distinct_issue_types() -> None:
    document = ResearchDocument(
        paper_id="paper-harness-001",
        source_hash="sha256-assets",
        sections=[
            ResearchSection(
                section_id="sec-method",
                title="Method",
                source_ref="paper://paper-harness-001/sec-method",
            )
        ],
        tables=[
            ResearchTable(
                table_id="table-1",
                caption="Ablation",
                columns=["model", "score"],
                rows=[{"model": "Harness", "unexpected": "extra"}],
                source_ref="paper://paper-harness-001/table-1",
            )
        ],
        equations=[
            ResearchEquation(
                equation_id="eq-1",
                latex="placeholder ??",
                source_ref="paper://paper-harness-001/eq-1",
            )
        ],
        lineage=SourceLineage(source_refs=["paper://paper-harness-001/sec-method"]),
    )
    payload = _payload_with_document(document)

    issue_types = {issue.issue_type for issue in ReaderRepairIssueDetector().detect(payload)}

    assert "table_parse_error" in issue_types
    assert "formula_render_error" in issue_types
