from __future__ import annotations

from interfaces.services.daily_approval_resume_projection import (
    project_daily_approval_resume_context,
)


def test_project_daily_approval_resume_context_adds_namespaced_route_patch() -> None:
    projected = project_daily_approval_resume_context(
        {
            "approval_id": "approval-1",
            "decision_payload": {
                "decision": "approved",
                "decision_type": "modify",
                "status": "modified",
                "approval_id": "approval-1",
                "modifications": {"summary": "tighten lead"},
            },
            "resume_metadata": {"approval_id": "approval-1"},
        },
        workflow_step_ids=["writer_agent", "finalize_report"],
        workflow_buffer_keys=[
            "human_review_resume_route",
            "quality.human_review_resume_route",
        ],
    )

    route = projected["human_review_resume_route"]
    assert route["route"] == "rewrite"
    assert route["next_step_id"] == "writer_agent"
    assert route["modifications"] == {"summary": "tighten lead"}
    assert projected["buffer_updates"]["human_review_resume_route"] == route
    assert projected["buffer_updates"]["quality.human_review_resume_route"] == route
    assert projected["resume_metadata"]["human_review_resume_route"] == route
    assert projected["resume_metadata"]["resume_next_step_id"] == "writer_agent"
