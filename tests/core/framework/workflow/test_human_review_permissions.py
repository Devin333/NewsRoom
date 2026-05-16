from __future__ import annotations

from core.framework.workflow import (
    HumanReviewActor,
    HumanReviewDecision,
    HumanReviewPermissionChecker,
    HumanReviewRequest,
)


def test_human_review_permission_rejects_missing_required_role() -> None:
    checker = HumanReviewPermissionChecker()

    allowed = checker.can_decide(
        actor=HumanReviewActor(actor_id="writer", roles=["writer"], permissions=[]),
        request=_request(required_role="editor"),
        decision=HumanReviewDecision(decision="approved", actor_id="writer"),
    )

    assert allowed is False


def test_human_review_permission_rejects_missing_required_permission() -> None:
    checker = HumanReviewPermissionChecker()

    allowed = checker.can_decide(
        actor=HumanReviewActor(actor_id="editor", roles=["editor"], permissions=[]),
        request=_request(
            required_role="editor",
            metadata={"required_permission": "reports.approve"},
        ),
        decision=HumanReviewDecision(decision="approved", actor_id="editor"),
    )

    assert allowed is False


def test_human_review_permission_allows_workflow_admin_override() -> None:
    checker = HumanReviewPermissionChecker()

    allowed = checker.can_decide(
        actor=HumanReviewActor(actor_id="admin", roles=["workflow_admin"], permissions=[]),
        request=_request(
            required_role="editor",
            metadata={"required_permission": "reports.approve"},
        ),
        decision=HumanReviewDecision(decision="approved", actor_id="admin"),
    )

    assert allowed is True


def _request(
    *,
    required_role: str | None,
    metadata: dict | None = None,
) -> HumanReviewRequest:
    return HumanReviewRequest(
        request_id="human_review:run-1:review:cp-1",
        run_id="run-1",
        step_id="review",
        workflow_id="daily",
        workflow_version="1.0",
        checkpoint_id="cp-1",
        review_type="editorial",
        required_role=required_role,
        created_at="2026-05-16T01:02:03Z",
        expires_at=None,
        inputs={"request": {"topic": "ai"}},
        metadata=metadata or {},
    )
