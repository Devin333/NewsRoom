from __future__ import annotations

from typing import Any

from business.boards.cross_board.workflows.daily_intelligence.agent_feedback_models import (
    PUBLICATION_GATE_TARGET,
    SOURCE_RECOLLECT_TARGET,
    DailyAgentFeedbackSummary,
)
from business.boards.cross_board.workflows.daily_intelligence.agents import (
    EDITOR_AGENT_ID,
    WRITER_AGENT_ID,
)


MAX_AGENT_FEEDBACK_REWRITE_ROUNDS = 1
MAX_AGENT_FEEDBACK_SOURCE_RECOLLECT_ROUNDS = 1


class DailyAgentFeedbackRoutingService:
    def next_loop_state(
        self,
        *,
        previous_loop_state: dict[str, Any],
        summary: DailyAgentFeedbackSummary,
        agent_reroute_allowed: bool,
    ) -> dict[str, Any]:
        previous_rewrite_rounds = _int_value(
            previous_loop_state.get("rewrite_rounds"),
            default=0,
        )
        previous_source_recollect_rounds = _int_value(
            previous_loop_state.get("source_recollect_rounds"),
            default=0,
        )
        source_recollect_requested = (
            agent_reroute_allowed and _source_recollect_requested(summary)
        )
        source_recollect_exhausted = (
            source_recollect_requested
            and previous_source_recollect_rounds >= MAX_AGENT_FEEDBACK_SOURCE_RECOLLECT_ROUNDS
        )
        source_recollect_rounds = previous_source_recollect_rounds
        if source_recollect_requested and not source_recollect_exhausted:
            source_recollect_rounds += 1
        rewrite_requested = (
            agent_reroute_allowed
            and not source_recollect_requested
            and _writer_rewrite_requested(summary)
        )
        rewrite_exhausted = (
            rewrite_requested
            and previous_rewrite_rounds >= MAX_AGENT_FEEDBACK_REWRITE_ROUNDS
        )
        rewrite_rounds = previous_rewrite_rounds
        if rewrite_requested and not rewrite_exhausted:
            rewrite_rounds += 1
        return {
            "rewrite_rounds": rewrite_rounds,
            "max_rewrite_rounds": MAX_AGENT_FEEDBACK_REWRITE_ROUNDS,
            "rewrite_requested": rewrite_requested,
            "rewrite_exhausted": rewrite_exhausted,
            "source_recollect_rounds": source_recollect_rounds,
            "max_source_recollect_rounds": MAX_AGENT_FEEDBACK_SOURCE_RECOLLECT_ROUNDS,
            "source_recollect_requested": source_recollect_requested,
            "source_recollect_exhausted": source_recollect_exhausted,
        }

    def route(
        self,
        *,
        summary: DailyAgentFeedbackSummary,
        loop_state: dict[str, Any],
        editor_review_available: bool,
    ) -> dict[str, Any]:
        if (
            not editor_review_available
            and loop_state["source_recollect_requested"]
            and not loop_state["source_recollect_exhausted"]
        ):
            return {
                "decision": "source_recollect_required",
                "next_step_id": "recollect_sources",
                "target_agent_id": SOURCE_RECOLLECT_TARGET,
                "policy_target_id": SOURCE_RECOLLECT_TARGET,
                "reason": "agent feedback requested source recollection planning",
                "source_recollect_round": loop_state["source_recollect_rounds"],
                "max_source_recollect_rounds": loop_state["max_source_recollect_rounds"],
            }
        if (
            not editor_review_available
            and loop_state["source_recollect_requested"]
            and loop_state["source_recollect_exhausted"]
        ):
            return {
                "decision": "blocked",
                "next_step_id": "finalize_report",
                "target_agent_id": PUBLICATION_GATE_TARGET,
                "policy_target_id": SOURCE_RECOLLECT_TARGET,
                "reason": "agent feedback source recollection rounds exhausted",
                "source_recollect_round": loop_state["source_recollect_rounds"],
                "max_source_recollect_rounds": loop_state["max_source_recollect_rounds"],
            }
        if (
            not editor_review_available
            and loop_state["rewrite_requested"]
            and not loop_state["rewrite_exhausted"]
        ):
            return {
                "decision": "retry_required",
                "next_step_id": "writer_agent",
                "target_agent_id": WRITER_AGENT_ID,
                "reason": "agent feedback requested writer rewrite",
                "rewrite_round": loop_state["rewrite_rounds"],
                "max_rewrite_rounds": loop_state["max_rewrite_rounds"],
            }
        if (
            not editor_review_available
            and loop_state["rewrite_requested"]
            and loop_state["rewrite_exhausted"]
        ):
            return {
                "decision": "blocked",
                "next_step_id": "finalize_report",
                "target_agent_id": PUBLICATION_GATE_TARGET,
                "reason": "agent feedback rewrite rounds exhausted",
                "rewrite_round": loop_state["rewrite_rounds"],
                "max_rewrite_rounds": loop_state["max_rewrite_rounds"],
            }
        if summary.block_request_count:
            return {
                "decision": "blocked",
                "next_step_id": "finalize_report",
                "target_agent_id": PUBLICATION_GATE_TARGET,
                "reason": "agent feedback requested publication block",
                "rewrite_round": loop_state["rewrite_rounds"],
                "max_rewrite_rounds": loop_state["max_rewrite_rounds"],
            }
        next_step_id = "finalize_report" if editor_review_available else "editor_agent"
        target_agent_id = "daily.finalize_report" if editor_review_available else EDITOR_AGENT_ID
        return {
            "decision": "pass",
            "next_step_id": next_step_id,
            "target_agent_id": target_agent_id,
            "reason": "no bounded agent feedback retry required",
            "rewrite_round": loop_state["rewrite_rounds"],
            "max_rewrite_rounds": loop_state["max_rewrite_rounds"],
        }


def _source_recollect_requested(summary: DailyAgentFeedbackSummary) -> bool:
    if summary.source_recollect_request_count <= 0:
        return False
    for recommendation in summary.policy_recommendations:
        if (
            recommendation.recommended_action == "source_recollect"
            and recommendation.target_agent_id == SOURCE_RECOLLECT_TARGET
        ):
            return True
    return SOURCE_RECOLLECT_TARGET in summary.target_agent_ids


def _writer_rewrite_requested(summary: DailyAgentFeedbackSummary) -> bool:
    if summary.rewrite_request_count <= 0:
        return False
    for recommendation in summary.policy_recommendations:
        if (
            recommendation.recommended_action == "rewrite"
            and recommendation.target_agent_id == WRITER_AGENT_ID
        ):
            return True
    return WRITER_AGENT_ID in summary.target_agent_ids


def _int_value(value: Any, *, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


__all__ = [
    "DailyAgentFeedbackRoutingService",
    "MAX_AGENT_FEEDBACK_REWRITE_ROUNDS",
    "MAX_AGENT_FEEDBACK_SOURCE_RECOLLECT_ROUNDS",
]
