from __future__ import annotations

from business.boards.cross_board.workflows.daily_intelligence.human_review_resume import (
    build_daily_human_review_resume_route,
    enrich_daily_approval_resume_context,
)


def test_daily_human_review_resume_route_maps_approval_to_publish() -> None:
    route = build_daily_human_review_resume_route(
        {
            "decision_payload": {
                "decision": "approved",
                "decision_type": "approve",
                "approval_id": "approval-1",
                "decided_by": "editor",
                "reason": "ready",
            }
        },
        workflow_step_ids=["writer_agent", "finalize_report"],
    )

    assert route is not None
    assert route.to_dict() == {
        "decision": "approved",
        "route": "final",
        "quality_route": "final",
        "next_step_id": "finalize_report",
        "publication_allowed": True,
        "rewrite_required": False,
        "reason": "ready",
        "approval_id": "approval-1",
        "decided_by": "editor",
        "modifications": {},
    }


def test_daily_human_review_resume_route_maps_rejection_to_blocked() -> None:
    route = build_daily_human_review_resume_route(
        {
            "decision_payload": {
                "decision": "rejected",
                "decision_type": "reject",
                "approval_id": "approval-2",
            }
        },
        workflow_step_ids=["writer_agent", "finalize_report"],
    )

    assert route is not None
    assert route.route == "blocked"
    assert route.quality_route == "blocked"
    assert route.next_step_id == "finalize_report"
    assert route.publication_allowed is False


def test_daily_human_review_resume_context_projects_modify_to_rewrite_route() -> None:
    context = enrich_daily_approval_resume_context(
        {
            "decision_payload": {
                "decision": "approved",
                "decision_type": "modify",
                "status": "modified",
                "approval_id": "approval-3",
                "modifications": {"summary": "tighten lead"},
            },
            "buffer_updates": {
                "human_review_decision": {
                    "decision": "approved",
                    "approval_id": "approval-3",
                }
            },
            "resume_metadata": {"approval_id": "approval-3"},
        },
        workflow_step_ids=["writer_agent", "finalize_report"],
    )

    route = context["human_review_resume_route"]
    assert route["decision"] == "needs_changes"
    assert route["route"] == "rewrite"
    assert route["next_step_id"] == "writer_agent"
    assert route["modifications"] == {"summary": "tighten lead"}
    assert context["buffer_updates"]["human_review_resume_route"] == route
    assert context["buffer_updates"]["quality.human_review_resume_route"] == route
    assert context["resume_metadata"]["human_review_resume_route"] == route
    assert context["resume_metadata"]["resume_next_step_id"] == "writer_agent"
    assert context["resume_metadata"]["allowed_patch_keys"] == [
        "human_review_resume_route",
        "quality.human_review_resume_route",
    ]


def test_daily_human_review_resume_context_skips_route_patch_for_unsupported_workflow() -> None:
    context = enrich_daily_approval_resume_context(
        {
            "decision_payload": {
                "decision": "approved",
                "decision_type": "approve",
                "approval_id": "approval-4",
            },
            "buffer_updates": {
                "human_review_decision": {
                    "decision": "approved",
                    "approval_id": "approval-4",
                }
            },
            "resume_metadata": {"approval_id": "approval-4"},
        },
        workflow_step_ids=["write_report"],
        workflow_buffer_keys=["final_report", "report_markdown"],
    )

    assert context["human_review_resume_route"]["route"] == "final"
    assert context["buffer_updates"] == {
        "human_review_decision": {
            "decision": "approved",
            "approval_id": "approval-4",
        }
    }
    assert "resume_next_step_id" not in context["resume_metadata"]
    assert "allowed_patch_keys" not in context["resume_metadata"]
