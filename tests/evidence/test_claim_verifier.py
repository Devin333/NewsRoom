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


def test_claim_verifier_marks_unmapped_claims_uncertain() -> None:
    findings = ClaimVerifier().verify(
        ["A policy outcome remains unclear."],
        _bundle(),
    )

    assert findings.uncertain_claims[0].status == "uncertain"
    assert findings.uncertain_claims[0].notes == "claim has no direct evidence mapping"
