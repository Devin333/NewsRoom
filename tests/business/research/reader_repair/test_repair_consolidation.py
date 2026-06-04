from __future__ import annotations

from business.research.domain import ReaderIssue
from business.research.reader_repair import ReaderRepairConsolidator
from tests.business.research.reader_repair._fixtures import make_repair_case


def test_similar_successful_cases_consolidate_to_procedural_strategy_seed_without_publishing_skill() -> None:
    issue = ReaderIssue(
        issue_id="issue-table",
        paper_id="paper-1",
        issue_type="table_parse_error",
        error_signature="table-sig",
        symptom="Table parse failed.",
        source_refs=["paper://paper-1/table-1"],
        payload_ref="payload-before",
    )
    cases = [
        make_repair_case("case-success-1", issue=issue, successful=True),
        make_repair_case("case-success-2", issue=issue, successful=True),
        make_repair_case("case-failed", issue=issue, successful=False),
    ]

    consolidator = ReaderRepairConsolidator()
    strategies = consolidator.consolidate(cases, min_cases=2, min_success_rate=0.5)
    seed = consolidator.skill_candidate_seed(strategies[0])

    assert strategies[0].status == "promoted_memory"
    assert seed is not None
    assert seed.publishes_skill is False
    assert seed.metadata["requires_harness_skill_evolution"] is True
