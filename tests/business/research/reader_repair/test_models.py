from __future__ import annotations

from business.research.domain import ReaderIssue, ReaderRepairCase, ReaderRepairStrategy, SourceLineage
from business.research.domain.reader_repair import ReaderRepairContextPack
from business.research.services import ReaderRepairGate


def test_reader_repair_models_are_serializable_and_do_not_publish_skill() -> None:
    issue = ReaderIssue(
        issue_id="issue-1",
        paper_id="paper-1",
        issue_type="table_parse_error",
        severity="high",
        error_signature="table_parse_error:missing_cells",
        symptom="The reader table dropped cells.",
        source_refs=["paper://paper-1/table-1"],
        payload_ref="reader-payload-1",
    )
    case = ReaderRepairCase(
        repair_case_id="repair-case-1",
        issue=issue,
        repair_strategy="Reparse the table with column count validation.",
        successful=True,
        payload_before_ref="reader-payload-1",
        payload_after_ref="reader-payload-2",
        source_refs=["paper://paper-1/table-1"],
    )
    strategy = ReaderRepairStrategy(
        strategy_id="strategy-table-reparse",
        issue_type="table_parse_error",
        applicability="Malformed table cell alignment.",
        steps=["detect column count", "reparse table", "verify source refs"],
        confidence=0.8,
        source_case_refs=[case.repair_case_id],
    )
    context = ReaderRepairContextPack(
        context_id="repair-context-1",
        issue=issue,
        recalled_cases=[case],
        candidate_strategies=[strategy],
        source_lineage=SourceLineage(source_refs=["paper://paper-1/table-1"]),
    )

    assert context.to_dict()["candidate_strategies"][0]["strategy_id"] == "strategy-table-reparse"
    assert all(result.passed for result in ReaderRepairGate().verify_case(case))


def test_reader_repair_gate_blocks_active_skill_mutation() -> None:
    issue = ReaderIssue(
        issue_id="issue-2",
        paper_id="paper-1",
        issue_type="reader_payload_schema_error",
        error_signature="schema_error",
        symptom="Payload violates schema.",
    )
    case = ReaderRepairCase(
        repair_case_id="repair-case-2",
        issue=issue,
        repair_strategy="Fix schema field.",
        successful=False,
        payload_before_ref="reader-payload-1",
        metadata={"active_skill_mutation": True},
    )

    results = ReaderRepairGate().verify_case(case)

    assert any(result.gate_name == "ReaderRepairSkillMutationGate" and not result.passed for result in results)
