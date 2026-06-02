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
    assert output["agent_feedback_route"]["decision"] == "pass"
    assert output["agent_feedback_route"]["next_step_id"] == "finalize_report"
    assert output["agent_feedback_route"]["target_agent_id"] == "daily.finalize_report"
    assert output["agent_feedback_loop_state"] == {
        "rewrite_rounds": 0,
        "max_rewrite_rounds": 1,
        "rewrite_requested": False,
        "rewrite_exhausted": False,
        "source_recollect_rounds": 0,
        "max_source_recollect_rounds": 1,
        "source_recollect_requested": False,
        "source_recollect_exhausted": False,
    }


def test_collect_agent_feedback_reads_namespaced_quality_and_feedback_keys() -> None:
    output = collect_agent_feedback(
        DataBuffer(
            {
                "quality.verification_result": {
                    "status": "needs_rewrite",
                    "risk_level": "medium",
                    "unsupported_claims": ["unsupported claim"],
                    "missing_citations": [],
                    "reasons": ["rewrite unsupported claim"],
                },
                "quality.citation_check_result": {},
                "quality.support_matrix": {},
                "agent.feedback.loop_state": {
                    "rewrite_rounds": 1,
                    "max_rewrite_rounds": 1,
                    "rewrite_requested": True,
                    "rewrite_exhausted": False,
                },
            }
        ).scope(
            read_keys=[
                "quality.verification_result",
                "quality.citation_check_result",
                "quality.support_matrix",
            ],
            optional_read_keys=["agent.feedback.loop_state"],
            write_keys=[],
        )
    )

    assert output["agent_feedback_route"]["decision"] == "blocked"
    assert output["agent_feedback_route"]["reason"] == "agent feedback rewrite rounds exhausted"
    assert output["agent_feedback_loop_state"]["rewrite_exhausted"] is True


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
    assert output["agent_feedback_route"]["decision"] == "blocked"
    assert output["agent_feedback_route"]["next_step_id"] == "finalize_report"


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
    assert output["agent_feedback_route"]["decision"] == "pass"
    assert output["agent_feedback_route"]["next_step_id"] == "finalize_report"


def test_collect_agent_feedback_routes_clean_verifier_pass_to_editor() -> None:
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
            editor_review=None,
        )
    )

    assert output["agent_feedback_events"] == []
    assert output["agent_feedback_route"]["decision"] == "pass"
    assert output["agent_feedback_route"]["next_step_id"] == "editor_agent"
    assert output["agent_feedback_route"]["target_agent_id"] == "daily.editor"


def test_collect_agent_feedback_can_route_verifier_feedback_before_editor_runs() -> None:
    output = collect_agent_feedback(
        _feedback_buffer(
            verification_result={
                "status": "needs_rewrite",
                "risk_level": "medium",
                "unsupported_claims": ["unsupported claim"],
                "missing_citations": [],
                "reasons": ["rewrite unsupported claim"],
            },
            citation_check_result={},
            support_matrix={},
            editor_review=None,
        )
    )

    assert [event.feedback_type for event in output["agent_feedback_events"]] == [
        "verification_rewrite_request"
    ]
    assert output["agent_feedback_route"]["decision"] == "retry_required"
    assert output["agent_feedback_route"]["next_step_id"] == "writer_agent"
    assert output["agent_feedback_route"]["target_agent_id"] == "daily.writer"
    assert output["agent_feedback_loop_state"]["rewrite_rounds"] == 1


def test_collect_agent_feedback_routes_analyst_evidence_gap_to_planner() -> None:
    output = collect_agent_feedback(
        _feedback_buffer(
            analysis_result={
                "findings": [],
                "trend_signals": [],
                "risk_notes": [],
                "uncertainty_notes": [],
                "evidence_gaps": [
                    {"reason": "Need a second independent source for model launch timing."}
                ],
                "source_recollection_requests": [
                    {"query": "model launch timing official announcement"}
                ],
                "missing_information": ["official launch date confirmation"],
            },
            verification_result={
                "status": "pass",
                "risk_level": "low",
                "unsupported_claims": [],
                "missing_citations": [],
                "reasons": [],
            },
            citation_check_result={},
            support_matrix={},
            editor_review=None,
        )
    )

    events = output["agent_feedback_events"]
    summary = output["agent_feedback_summary"]

    assert [event.feedback_type for event in events] == ["source_recollection_request"]
    assert events[0].source_agent_id == "daily.analyst"
    assert events[0].target_agent_id == "daily.source_recollect"
    assert events[0].requested_action == "source_recollect"
    assert events[0].reason == "model launch timing official announcement"
    assert summary.source_recollect_request_count == 1
    assert summary.policy_recommendations[0].recommended_action == "source_recollect"
    assert summary.policy_recommendations[0].target_agent_id == "daily.source_recollect"
    assert output["agent_feedback_route"]["decision"] == "source_recollect_required"
    assert output["agent_feedback_route"]["next_step_id"] == "planner_agent"
    assert output["agent_feedback_route"]["target_agent_id"] == "daily.planner"
    assert output["agent_feedback_route"]["policy_target_id"] == "daily.source_recollect"
    assert output["agent_feedback_loop_state"]["source_recollect_rounds"] == 1
    assert output["agent_feedback_loop_state"]["rewrite_rounds"] == 0


def test_collect_agent_feedback_exhausts_bounded_source_recollect_loop() -> None:
    output = collect_agent_feedback(
        _feedback_buffer(
            analysis_result={
                "findings": [],
                "trend_signals": [],
                "risk_notes": [],
                "uncertainty_notes": [],
                "evidence_gaps": [{"reason": "Need a primary source."}],
            },
            verification_result={
                "status": "pass",
                "risk_level": "low",
                "unsupported_claims": [],
                "missing_citations": [],
                "reasons": [],
            },
            citation_check_result={},
            support_matrix={},
            editor_review=None,
            agent_feedback_loop_state={
                "rewrite_rounds": 0,
                "max_rewrite_rounds": 1,
                "rewrite_requested": False,
                "rewrite_exhausted": False,
                "source_recollect_rounds": 1,
                "max_source_recollect_rounds": 1,
                "source_recollect_requested": True,
                "source_recollect_exhausted": False,
            },
        )
    )

    assert output["agent_feedback_route"]["decision"] == "blocked"
    assert output["agent_feedback_route"]["next_step_id"] == "finalize_report"
    assert output["agent_feedback_route"]["reason"] == (
        "agent feedback source recollection rounds exhausted"
    )
    assert output["agent_feedback_loop_state"]["source_recollect_rounds"] == 1
    assert output["agent_feedback_loop_state"]["source_recollect_exhausted"] is True


def test_collect_agent_feedback_exhausts_bounded_writer_rewrite_loop() -> None:
    output = collect_agent_feedback(
        _feedback_buffer(
            verification_result={
                "status": "needs_rewrite",
                "risk_level": "medium",
                "unsupported_claims": ["unsupported claim"],
                "missing_citations": [],
                "reasons": ["rewrite unsupported claim"],
            },
            citation_check_result={},
            support_matrix={},
            editor_review=None,
            agent_feedback_loop_state={
                "rewrite_rounds": 1,
                "max_rewrite_rounds": 1,
                "rewrite_requested": True,
                "rewrite_exhausted": False,
            },
        )
    )

    assert output["agent_feedback_route"]["decision"] == "blocked"
    assert output["agent_feedback_route"]["next_step_id"] == "finalize_report"
    assert output["agent_feedback_route"]["reason"] == "agent feedback rewrite rounds exhausted"
    assert output["agent_feedback_loop_state"]["rewrite_rounds"] == 1
    assert output["agent_feedback_loop_state"]["rewrite_exhausted"] is True


def _feedback_buffer(
    *,
    analysis_result: dict | None = None,
    verification_result: dict,
    citation_check_result: dict,
    support_matrix: dict,
    editor_review: dict | None,
    agent_feedback_loop_state: dict | None = None,
):
    values = {
        "analysis_result": analysis_result or {},
        "verification_result": verification_result,
        "citation_check_result": citation_check_result,
        "support_matrix": support_matrix,
    }
    if editor_review is not None:
        values["editor_review"] = editor_review
    if agent_feedback_loop_state is not None:
        values["agent_feedback_loop_state"] = agent_feedback_loop_state
    return DataBuffer(values).scope(
        read_keys=[
            "analysis_result",
            "verification_result",
            "citation_check_result",
            "support_matrix",
            "editor_review",
            "agent_feedback_loop_state",
        ],
        write_keys=[],
    )
