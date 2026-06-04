from __future__ import annotations

from business.research.taxonomy import TaxonomyAssignmentBuilder, TaxonomyCandidate, TaxonomyRegistry, validate_taxonomy_candidate


def test_taxonomy_candidate_must_exist_in_registry() -> None:
    registry = TaxonomyRegistry.default()
    accepted = TaxonomyCandidate(
        candidate_id="tax-1",
        level="task",
        term_id="paper_reading",
        label="paper reading",
        evidence_refs=["paper://paper-1/sec-intro"],
        confidence=0.8,
    )
    invented = TaxonomyCandidate(
        candidate_id="tax-2",
        level="task",
        term_id="invented_task",
        label="invented task",
        evidence_refs=["paper://paper-1/sec-intro"],
        confidence=0.7,
    )

    assert validate_taxonomy_candidate(accepted, registry).passed is True
    assert validate_taxonomy_candidate(invented, registry).passed is False

    assignment = TaxonomyAssignmentBuilder(registry).build("paper-1", [accepted, invented])
    assert assignment.accepted_candidate_ids == ["tax-1"]
    assert assignment.review_candidate_ids == ["tax-2"]
