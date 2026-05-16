from __future__ import annotations

import pytest

from core.framework.workflow import HumanReviewDecision


def test_human_review_decision_accepts_approved() -> None:
    decision = HumanReviewDecision.from_dict(
        {
            "decision": "approved",
            "actor_id": "editor",
            "reason": "looks good",
        }
    )

    assert decision.decision == "approved"
    assert decision.actor_id == "editor"
    assert decision.to_dict()["reason"] == "looks good"


def test_human_review_decision_rejects_unknown_decision() -> None:
    with pytest.raises(ValueError, match="invalid human review decision"):
        HumanReviewDecision.from_dict(
            {"decision": "defer", "actor_id": "editor"}
        )


def test_human_review_decision_requires_actor_id() -> None:
    with pytest.raises(ValueError, match="actor_id"):
        HumanReviewDecision.from_dict(
            {"decision": "approved", "actor_id": ""}
        )


def test_human_review_decision_rejects_non_dict_patch() -> None:
    with pytest.raises(ValueError, match="patch"):
        HumanReviewDecision.from_dict(
            {
                "decision": "needs_changes",
                "actor_id": "editor",
                "patch": ["not", "an", "object"],
            }
        )


def test_human_review_decision_roundtrip() -> None:
    payload = {
        "decision": "needs_changes",
        "actor_id": "editor",
        "reason": "tighten citations",
        "patch": {"revision_note": "add source labels"},
        "decided_at": "2026-05-16T01:02:03Z",
        "metadata": {"ticket": "review-1"},
    }

    decision = HumanReviewDecision.from_dict(payload)

    assert decision.to_dict() == payload
