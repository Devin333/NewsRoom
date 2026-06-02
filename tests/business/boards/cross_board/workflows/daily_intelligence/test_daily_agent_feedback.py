from __future__ import annotations

from framework.workflow import DataBuffer
from business.boards.cross_board.workflows.daily_intelligence.agent_feedback import collect_agent_feedback


def test_collect_agent_feedback_records_verifier_and_editor_rewrite_requests() -> None:
    output = collect_agent_feedback(
        _feedback_buffer(
            verification_result={
                "status": "needs_rewrite",
                "risk_level": "medium",
                "unsupported_claims": ["Unsupported market impact claim"],
                "missing_citations": ["summary"],
                "reasons": ["unsupported claim needs rewrite"],
            },
            citation_check_result={
                "unsupported_urls": ["https://outside.example/item"],
                "unknown_urls": [],
            },
            support_matrix={"unsupported_sections": ["summary"]},
            editor_review={
                "decision": "rewrite_required",
                "quality_score": 0.55,
                "reasons": ["remove unsupported market impact"],
                "rewrite_instructions": ["remove unsupported market impact"],
            },
        )
    )

    events = output["agent_feedback_events"]
    summary = output["agent_feedback_summary"]

    assert output["agent.feedback.events"] == events
    assert output["agent.feedback.summary"] == summary
    assert [event.feedback_type for event in events] == [
        "verification_rewrite_request",
        "missing_citation_feedback",
        "evidence_boundary_feedback",
        "editor_rewrite_request",
    ]
    assert all(event.target_agent_id == "daily.writer" for event in events)
    assert summary.event_count == 4
    assert summary.rewrite_request_count == 4
    assert summary.highest_severity == "warning"
    assert summary.target_agent_ids == ["daily.writer"]
    assert [recommendation.recommended_action for recommendation in summary.policy_recommendations] == ["rewrite"]
    assert summary.policy_recommendations[0].target_agent_id == "daily.writer"
    assert summary.policy_recommendations[0].source_feedback_ids == [
        "daily-agent-feedback-1",
        "daily-agent-feedback-2",
        "daily-agent-feedback-3",
        "daily-agent-feedback-4",
    ]
    assert summary.metadata["policy_recommendation_count"] == 1


def test_collect_agent_feedback_records_block_and_human_review_targets() -> None:
    output = collect_agent_feedback(
        _feedback_buffer(
            verification_result={
                "status": "blocked",
                "risk_level": "high",
                "unsupported_claims": [],
                "missing_citations": [],
                "reasons": ["citation boundary failed"],
            },
            citation_check_result={},
            support_matrix={},
            editor_review={
                "decision": "human_review_required",
                "quality_score": 0.75,
                "reasons": ["manual approval required"],
                "rewrite_instructions": [],
            },
        )
    )

    events = output["agent_feedback_events"]
    summary = output["agent_feedback_summary"]

    assert [event.requested_action for event in events] == ["block", "human_review"]
    assert summary.block_request_count == 1
    assert summary.human_review_request_count == 1
    assert summary.highest_severity == "block"
    assert summary.target_agent_ids == ["daily.publication_gate", "daily.human_review"]
    assert [recommendation.recommended_action for recommendation in summary.policy_recommendations] == [
        "block",
        "human_review",
    ]
    assert [recommendation.target_agent_id for recommendation in summary.policy_recommendations] == [
        "daily.publication_gate",
        "daily.human_review",
    ]
    assert summary.policy_recommendations[0].priority == "block"


def test_collect_agent_feedback_returns_empty_summary_for_clean_pass() -> None:
    output = collect_agent_feedback(
        _feedback_buffer(
            verification_result={
                "status": "pass",
                "risk_level": "low",
                "unsupported_claims": [],
                "missing_citations": [],
                "reasons": [],
            },
            citation_check_result={},
            support_matrix={},
            editor_review={
                "decision": "pass",
                "quality_score": 0.95,
                "reasons": [],
                "rewrite_instructions": [],
            },
        )
    )

    assert output["agent_feedback_events"] == []
    assert output["agent_feedback_summary"].event_count == 0
    assert output["agent_feedback_summary"].highest_severity == "none"
    assert output["agent_feedback_summary"].policy_recommendations == []


def _feedback_buffer(
    *,
    verification_result: dict,
    citation_check_result: dict,
    support_matrix: dict,
    editor_review: dict,
):
    return DataBuffer(
        {
            "verification_result": verification_result,
            "citation_check_result": citation_check_result,
            "support_matrix": support_matrix,
            "editor_review": editor_review,
        }
    ).scope(
        read_keys=[
            "verification_result",
            "citation_check_result",
            "support_matrix",
            "editor_review",
        ],
        write_keys=[],
    )
