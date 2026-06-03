from __future__ import annotations

from business.boards.cross_board.workflows.daily_intelligence.agent_feedback_models import (
    SOURCE_RECOLLECT_TARGET,
    DailyAgentFeedbackEvent,
    DailyAgentFeedbackPolicyRecommendation,
    DailyAgentFeedbackSummary,
)
from business.boards.cross_board.workflows.daily_intelligence.source_recollection import (
    DailySourceRecollectionService,
)
from business.boards.cross_board.workflows.daily_intelligence.source_recollection_execution import (
    DailySourceRecollectionExecutionService,
)


def test_build_profile_from_source_recollect_recommendation() -> None:
    profile = DailySourceRecollectionService().build_profile(
        events=[
            DailyAgentFeedbackEvent(
                feedback_id="daily-agent-feedback-1",
                source_agent_id="daily.analyst",
                target_agent_id=SOURCE_RECOLLECT_TARGET,
                feedback_type="source_recollection_request",
                severity="warning",
                requested_action="source_recollect",
                reason="Need launch timing confirmation.",
                evidence_gaps=[
                    {"reason": "Need a second independent source for launch timing."}
                ],
                source_recollection_requests=[
                    {"query": "model launch timing official announcement"}
                ],
                missing_information=["official launch date confirmation"],
            )
        ],
        summary=DailyAgentFeedbackSummary(
            event_count=1,
            source_recollect_request_count=1,
            target_agent_ids=[SOURCE_RECOLLECT_TARGET],
            policy_recommendations=[
                DailyAgentFeedbackPolicyRecommendation(
                    recommendation_id=(
                        "daily-agent-feedback-policy-source-recollect:daily.source_recollect"
                    ),
                    target_agent_id=SOURCE_RECOLLECT_TARGET,
                    recommended_action="source_recollect",
                    priority="warning",
                    reason="Need launch timing confirmation.",
                    source_feedback_ids=["daily-agent-feedback-1"],
                )
            ],
        ),
        route={
            "decision": "source_recollect_required",
            "next_step_id": "recollect_sources",
            "target_agent_id": SOURCE_RECOLLECT_TARGET,
            "policy_target_id": SOURCE_RECOLLECT_TARGET,
            "source_recollect_round": 1,
            "max_source_recollect_rounds": 1,
        },
        loop_state={
            "source_recollect_rounds": 1,
            "max_source_recollect_rounds": 1,
        },
    )

    assert profile is not None
    assert profile.profile_id == "daily-source-recollect-1"
    assert profile.target_id == SOURCE_RECOLLECT_TARGET
    assert profile.reason == "Need launch timing confirmation."
    assert profile.source_recollect_round == 1
    assert profile.max_source_recollect_rounds == 1
    assert profile.queries == [
        "model launch timing official announcement",
        "Need a second independent source for launch timing.",
        "official launch date confirmation",
    ]
    assert profile.source_feedback_ids == ["daily-agent-feedback-1"]
    assert profile.recommendation_ids == [
        "daily-agent-feedback-policy-source-recollect:daily.source_recollect"
    ]
    assert profile.query_count == 3
    assert profile.evidence_gap_count == 1
    assert profile.source_recollection_request_count == 1
    assert profile.missing_information_count == 1
    assert profile.metadata == {}
    plan = DailySourceRecollectionExecutionService().build_plan(profile)
    assert plan is not None
    assert plan.plan_id == "daily-source-recollect-1-execution-plan"
    assert plan.profile_id == profile.profile_id
    assert plan.status == "ready"
    assert plan.execution_mode == "source_fetch_execution_contract"
    assert plan.source_recollect_round == 1
    assert plan.max_source_recollect_rounds == 1
    assert plan.query_count == 3
    assert plan.task_count == 3
    assert [task.task_id for task in plan.tasks] == [
        "daily-source-recollect-1-task-01",
        "daily-source-recollect-1-task-02",
        "daily-source-recollect-1-task-03",
    ]
    assert [task.query for task in plan.tasks] == profile.queries
    assert all(task.status == "ready" for task in plan.tasks)
    assert all(task.source_feedback_ids == ["daily-agent-feedback-1"] for task in plan.tasks)
    assert plan.recommendation_ids == [
        "daily-agent-feedback-policy-source-recollect:daily.source_recollect"
    ]


def test_feedback_event_projects_legacy_source_recollection_metadata() -> None:
    event = DailyAgentFeedbackEvent(
        feedback_id="daily-agent-feedback-1",
        source_agent_id="daily.analyst",
        target_agent_id=SOURCE_RECOLLECT_TARGET,
        feedback_type="source_recollection_request",
        severity="warning",
        requested_action="source_recollect",
        reason="Need launch timing confirmation.",
        metadata={
            "evidence_gaps": [
                {"reason": "Need a second independent source for launch timing."}
            ],
            "source_recollection_requests": [
                {"query": "model launch timing official announcement"}
            ],
            "missing_information": ["official launch date confirmation"],
        },
    )

    assert event.evidence_gaps == [
        {"reason": "Need a second independent source for launch timing."}
    ]
    assert event.source_recollection_requests == [
        {"query": "model launch timing official announcement"}
    ]
    assert event.missing_information == ["official launch date confirmation"]


def test_profile_uses_feedback_event_projection_for_legacy_recollection_metadata() -> None:
    profile = DailySourceRecollectionService().build_profile(
        events=[
            DailyAgentFeedbackEvent(
                feedback_id="daily-agent-feedback-1",
                source_agent_id="daily.analyst",
                target_agent_id=SOURCE_RECOLLECT_TARGET,
                feedback_type="source_recollection_request",
                severity="warning",
                requested_action="source_recollect",
                reason="Need launch timing confirmation.",
                metadata={
                    "evidence_gaps": [
                        {"reason": "Need a second independent source for launch timing."}
                    ],
                    "source_recollection_requests": [
                        {"query": "model launch timing official announcement"}
                    ],
                    "missing_information": ["official launch date confirmation"],
                },
            )
        ],
        summary=DailyAgentFeedbackSummary(event_count=1, source_recollect_request_count=1),
        route={
            "decision": "source_recollect_required",
            "policy_target_id": SOURCE_RECOLLECT_TARGET,
            "source_recollect_round": 1,
            "max_source_recollect_rounds": 1,
        },
        loop_state={},
    )

    assert profile is not None
    assert profile.evidence_gaps == [
        {"reason": "Need a second independent source for launch timing."}
    ]
    assert profile.source_recollection_requests == [
        {"query": "model launch timing official announcement"}
    ]
    assert profile.missing_information == ["official launch date confirmation"]
    assert profile.queries == [
        "model launch timing official announcement",
        "Need a second independent source for launch timing.",
        "official launch date confirmation",
    ]


def test_build_profile_ignores_non_source_recollect_route() -> None:
    profile = DailySourceRecollectionService().build_profile(
        events=[
            DailyAgentFeedbackEvent(
                feedback_id="daily-agent-feedback-1",
                source_agent_id="daily.analyst",
                target_agent_id=SOURCE_RECOLLECT_TARGET,
                feedback_type="source_recollection_request",
                severity="warning",
                requested_action="source_recollect",
                reason="Need launch timing confirmation.",
            )
        ],
        summary=DailyAgentFeedbackSummary(event_count=1, source_recollect_request_count=1),
        route={"decision": "blocked", "policy_target_id": SOURCE_RECOLLECT_TARGET},
        loop_state={"source_recollect_rounds": 1},
    )

    assert profile is None


def test_build_execution_plan_returns_none_without_profile() -> None:
    assert DailySourceRecollectionExecutionService().build_plan(None) is None
