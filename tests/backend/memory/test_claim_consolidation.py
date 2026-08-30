from backend.memory.claim_consolidation import ClaimConsolidator
from backend.memory.intelligence_models import ClaimMemory


def test_duplicate_claim_merge_combines_evidence_and_confidence() -> None:
    existing = ClaimMemory(
        claim_id="claim-1",
        run_id="run-1",
        text="OpenAI released a model",
        confidence=0.5,
        evidence_ids=["ev-1"],
    )
    new = ClaimMemory(
        claim_id="claim-2",
        run_id="run-2",
        text=" openai released   a model ",
        confidence=0.6,
        evidence_ids=["ev-2"],
    )

    result = ClaimConsolidator().consolidate([new], [existing])

    assert result.counts()["merged"] == 1
    assert result.merged[0].claim_id == "claim-1"
    assert result.merged[0].evidence_ids == ["ev-1", "ev-2"]
    assert result.merged[0].confidence > existing.confidence


def test_contradiction_produces_contradicted_action() -> None:
    existing = ClaimMemory(
        claim_id="claim-1",
        run_id="run-1",
        text="OpenAI released a model",
        subject_entity_id="entity:openai",
        predicate="released",
        confidence=0.8,
        evidence_ids=["ev-1"],
    )
    new = ClaimMemory(
        claim_id="claim-2",
        run_id="run-2",
        text="OpenAI did not release a model",
        subject_entity_id="entity:openai",
        predicate="released",
        evidence_ids=["ev-2"],
    )

    result = ClaimConsolidator().consolidate([new], [existing])

    assert result.counts()["contradicted"] == 1
    assert result.actions[0].action_type == "contradict"
    assert result.contradicted[0].status == "contradicted"
    assert result.contradicted[0].contradicted_by == ["ev-2"]
