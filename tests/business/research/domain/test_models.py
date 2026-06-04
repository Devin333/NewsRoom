from __future__ import annotations

from business.research.domain import ResearchAnalysis, ResearchClaim, ResearchEvidencePack, SourceLineage
from tests.business.research.helpers import sample_document, sample_three_minute_read


def test_domain_models_are_serializable_and_keep_lineage() -> None:
    document = sample_document()
    claim = ResearchClaim(
        claim_id="claim-1",
        text="Harness controls routing.",
        claim_type="method",
        section_id="sec-intro",
        evidence_ids=["evidence-intro"],
        confidence=0.9,
    )
    evidence_pack = ResearchEvidencePack(
        pack_id="pack-1",
        paper_id="paper-1",
        items=[],
        coverage={"sections": 1.0},
        lineage=SourceLineage(source_refs=["paper://paper-1"], source_hash="sha256-paper-1"),
    )
    analysis = ResearchAnalysis(
        paper_id="paper-1",
        summary=sample_three_minute_read(),
        contributions=["Harness-owned gates"],
        claims=[claim],
        evidence_pack_id=evidence_pack.pack_id,
    )

    assert document.to_dict()["lineage"]["source_refs"] == ["paper://paper-1"]
    assert evidence_pack.to_dict()["coverage"]["sections"] == 1.0
    assert analysis.to_dict()["claims"][0]["evidence_ids"] == ["evidence-intro"]
