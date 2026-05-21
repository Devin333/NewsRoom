from __future__ import annotations

from framework.scoring import (
    FeatureVector,
    GateAction,
    GateRunner,
    GateSpec,
    ScoringContext,
    ScoringTarget,
)


def test_missing_feature_triggers_block() -> None:
    results = GateRunner().run(
        [GateSpec(gate_id="requires_evidence", action=GateAction.BLOCK, feature="evidence", operator="exists")],
        target=_target(),
        features=FeatureVector.from_scores({}),
        context=ScoringContext(),
    )

    assert results[0].passed is False
    assert results[0].blocked is True


def test_comparison_operators() -> None:
    gates = [
        GateSpec(gate_id="lt", action=GateAction.REVIEW, feature="risk", operator="lt", threshold=0.5),
        GateSpec(gate_id="gte", action=GateAction.REVIEW, feature="evidence", operator="gte", threshold=0.8),
        GateSpec(gate_id="between", action=GateAction.REVIEW, feature="freshness", operator="between", threshold=(0.2, 0.4)),
    ]

    results = GateRunner().run(
        gates,
        target=_target(),
        features=FeatureVector.from_scores({"risk": 0.4, "evidence": 0.8, "freshness": 0.3}),
        context=ScoringContext(),
    )

    assert [result.passed for result in results] == [True, True, True]


def test_cap_penalty_review_and_boost_effect_fields() -> None:
    gates = [
        GateSpec(gate_id="cap", action=GateAction.CAP, feature="evidence", operator="gte", threshold=0.5, score_cap=0.6),
        GateSpec(gate_id="penalty", action=GateAction.PENALTY, feature="risk", operator="lt", threshold=0.5, penalty=0.2),
        GateSpec(gate_id="review", action=GateAction.REVIEW, feature="signal", operator="exists"),
        GateSpec(gate_id="boost", action=GateAction.BOOST, feature="freshness", operator="gte", threshold=0.8, boost=0.1),
    ]

    results = GateRunner().run(
        gates,
        target=_target(),
        features=FeatureVector.from_scores({"evidence": 0.2, "risk": 0.8, "freshness": 0.9}),
        context=ScoringContext(),
    )

    assert results[0].score_cap == 0.6
    assert results[1].penalty == 0.2
    assert results[2].review_required is True
    assert results[3].boost == 0.1


def _target() -> ScoringTarget:
    return ScoringTarget(target_id="card-1", target_type="board_card")
