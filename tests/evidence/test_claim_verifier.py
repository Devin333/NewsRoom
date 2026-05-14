from evidence import Claim, ClaimVerifier, EvidenceBundle, EvidenceItem


def _bundle() -> EvidenceBundle:
    return EvidenceBundle(
        bundle_id="bundle",
        items=[
            EvidenceItem(
                evidence_id="ev_1",
                source_url="https://example.com/a",
                title="AI policy update",
                summary="Policy summary.",
                confidence=0.9,
                source_id="source",
            )
        ],
    )


def test_claim_verifier_rejects_claims_outside_evidence_bundle() -> None:
    findings = ClaimVerifier().verify(
        [
            Claim(
                claim_id="claim_outside",
                text="A vendor announced an unrelated acquisition.",
                claim_type="fact",
                source_urls=["https://example.com/outside"],
            )
        ],
        _bundle(),
    )

    assert findings.accepted_claims == []
    assert findings.rejected_claims[0].claim_id == "claim_outside"
    assert findings.rejected_claims[0].rejecting_sources == ["https://example.com/outside"]
    assert findings.rejected_claims[0].rejection_reason == "claim references evidence outside the bundle"


def test_claim_verifier_marks_unmapped_claims_uncertain() -> None:
    findings = ClaimVerifier().verify(
        ["A policy outcome remains unclear."],
        _bundle(),
    )

    assert findings.uncertain_claims[0].status == "uncertain"
    assert findings.uncertain_claims[0].notes == "claim has no direct evidence mapping"
    assert findings.uncertain_claims[0].uncertainty_reason == "claim has no direct evidence mapping"


def test_claim_extractor_extracts_section_claims_from_report() -> None:
    from evidence import ClaimExtractor

    claims = ClaimExtractor().extract(
        report_draft={
            "sections": [
                {
                    "section_id": "summary",
                    "title": "Summary",
                    "content": "AI policy update shipped. Critical vulnerability remains open.",
                    "sources": ["https://example.com/a"],
                    "evidence_ids": ["ev_1"],
                }
            ]
        }
    )

    assert [claim.section_id for claim in claims] == ["summary", "summary"]
    assert claims[0].source_evidence_ids == ["ev_1"]
    assert claims[1].severity == "high"


def test_claim_verifier_accepts_evidence_backed_claims() -> None:
    findings = ClaimVerifier().verify(
        [
            Claim(
                claim_id="claim_supported",
                text="AI policy update: Policy summary.",
                claim_type="fact",
                section_id="summary",
                severity="low",
                importance="medium",
                source_evidence_ids=["ev_1"],
            )
        ],
        _bundle(),
    )

    accepted = findings.accepted_claims[0]
    assert accepted.status == "accepted"
    assert accepted.supporting_evidence_ids == ["ev_1"]
    assert accepted.section_id == "summary"
