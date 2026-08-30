from backend.memory.adaptive_thresholds import AdaptiveThresholdSet, MemoryPolicyProposal


def test_memory_policy_proposal_blocks_high_risk_auto_apply() -> None:
    proposal = MemoryPolicyProposal(
        proposal_id="proposal-1",
        target="contradiction_block_threshold",
        old_value=0.8,
        new_value=0.7,
        reason="too many contradictions",
        confidence=0.9,
        risk_level="high",
        requires_human_approval=True,
    )

    assert proposal.can_auto_apply() is False
    assert proposal.to_dict()["requires_human_approval"] is True


def test_low_risk_policy_proposal_can_auto_apply_when_approval_not_required() -> None:
    proposal = MemoryPolicyProposal(
        proposal_id="proposal-2",
        target="duplicate_penalty_threshold",
        old_value=0.5,
        new_value=0.45,
        reason="event duplicate rate elevated",
        confidence=0.3,
        risk_level="low",
        requires_human_approval=False,
    )

    assert proposal.can_auto_apply() is True


def test_adaptive_threshold_defaults_match_memory_policy_baseline() -> None:
    thresholds = AdaptiveThresholdSet()

    assert thresholds.source_reliability_min == 0.3
    assert thresholds.claim_confidence_min == 0.5
    assert thresholds.contradiction_block_threshold == 0.8
