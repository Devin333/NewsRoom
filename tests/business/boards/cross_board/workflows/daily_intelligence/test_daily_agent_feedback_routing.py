from __future__ import annotations

from business.boards.cross_board.workflows.daily_intelligence.agent_feedback_models import (
    SOURCE_RECOLLECT_TARGET,
    DailyAgentFeedbackPolicyRecommendation,
    DailyAgentFeedbackSummary,
)
from business.boards.cross_board.workflows.daily_intelligence.agent_feedback_routing import (
    DailyAgentFeedbackRoutingService,
)


def test_routing_prefers_source_recollect_before_writer_rewrite() -> None:
    service = DailyAgentFeedbackRoutingService()
    summary = DailyAgentFeedbackSummary(
        event_count=2,
        rewrite_request_count=1,
        source_recollect_request_count=1,
        target_agent_ids=[SOURCE_RECOLLECT_TARGET, "daily.writer"],
        policy_recommendations=[
            _recommendation(
                action="source_recollect",
                target_agent_id=SOURCE_RECOLLECT_TARGET,
            ),
            _recommendation(action="rewrite", target_agent_id="daily.writer"),
        ],
    )

    loop_state = service.next_loop_state(
        previous_loop_state={},
        summary=summary,
        agent_reroute_allowed=True,
    )
    route = service.route(
        summary=summary,
        loop_state=loop_state,
        editor_review_available=False,
    )

    assert loop_state["source_recollect_requested"] is True
    assert loop_state["source_recollect_rounds"] == 1
    assert loop_state["rewrite_requested"] is False
    assert loop_state["rewrite_rounds"] == 0
    assert route["decision"] == "source_recollect_required"
    assert route["next_step_id"] == "planner_agent"
    assert route["policy_target_id"] == SOURCE_RECOLLECT_TARGET


def test_routing_blocks_when_source_recollect_round_is_exhausted() -> None:
    service = DailyAgentFeedbackRoutingService()
    summary = DailyAgentFeedbackSummary(
        event_count=1,
        source_recollect_request_count=1,
        target_agent_ids=[SOURCE_RECOLLECT_TARGET],
        policy_recommendations=[
            _recommendation(
                action="source_recollect",
                target_agent_id=SOURCE_RECOLLECT_TARGET,
            )
        ],
    )

    loop_state = service.next_loop_state(
        previous_loop_state={"source_recollect_rounds": 1},
        summary=summary,
        agent_reroute_allowed=True,
    )
    route = service.route(
        summary=summary,
        loop_state=loop_state,
        editor_review_available=False,
    )

    assert loop_state["source_recollect_requested"] is True
    assert loop_state["source_recollect_exhausted"] is True
    assert loop_state["source_recollect_rounds"] == 1
    assert route == {
        "decision": "blocked",
        "next_step_id": "finalize_report",
        "target_agent_id": "daily.publication_gate",
        "policy_target_id": SOURCE_RECOLLECT_TARGET,
        "reason": "agent feedback source recollection rounds exhausted",
        "source_recollect_round": 1,
        "max_source_recollect_rounds": 1,
    }


def _recommendation(
    *,
    action: str,
    target_agent_id: str,
) -> DailyAgentFeedbackPolicyRecommendation:
    return DailyAgentFeedbackPolicyRecommendation(
        recommendation_id=f"daily-agent-feedback-policy-{action}:{target_agent_id}",
        target_agent_id=target_agent_id,
        recommended_action=action,
        priority="warning",
        reason=f"{action} requested",
    )
