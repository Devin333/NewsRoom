from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

from business.boards.cross_board.workflows.daily_intelligence.buffer_key_aliases import (
    with_namespaced_aliases,
)


FINALIZE_STEP_ID = "finalize_report"
WRITER_STEP_ID = "writer_agent"
DRAFT_STEP_ID = "draft_report"


@dataclass(frozen=True)
class DailyHumanReviewResumeRoute:
    decision: str
    route: str
    quality_route: str
    next_step_id: str
    publication_allowed: bool
    rewrite_required: bool = False
    reason: str | None = None
    approval_id: str | None = None
    decided_by: str | None = None
    modifications: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "decision": self.decision,
            "route": self.route,
            "quality_route": self.quality_route,
            "next_step_id": self.next_step_id,
            "publication_allowed": self.publication_allowed,
            "rewrite_required": self.rewrite_required,
            "reason": self.reason,
            "approval_id": self.approval_id,
            "decided_by": self.decided_by,
            "modifications": dict(self.modifications),
        }


def build_daily_human_review_resume_route(
    approval_context: Mapping[str, Any],
    *,
    workflow_step_ids: Iterable[str] = (),
) -> DailyHumanReviewResumeRoute | None:
    decision_payload = _decision_payload(approval_context)
    if not decision_payload:
        return None
    decision = _text(decision_payload.get("decision"))
    decision_type = _text(decision_payload.get("decision_type"))
    status = _text(decision_payload.get("status"))
    modifications = _dict_value(decision_payload.get("modifications"))
    if decision in {"rejected", "reject"} or decision_type == "reject":
        route = "blocked"
        normalized_decision = "rejected"
        publication_allowed = False
        rewrite_required = False
    elif (
        decision in {"needs_changes", "needs_change", "modified"}
        or decision_type == "modify"
        or status == "modified"
        or bool(modifications)
    ):
        route = "rewrite"
        normalized_decision = "needs_changes"
        publication_allowed = False
        rewrite_required = True
    else:
        route = "final"
        normalized_decision = "approved"
        publication_allowed = True
        rewrite_required = False
    return DailyHumanReviewResumeRoute(
        decision=normalized_decision,
        route=route,
        quality_route=route,
        next_step_id=_next_step_id(route, tuple(str(step_id) for step_id in workflow_step_ids)),
        publication_allowed=publication_allowed,
        rewrite_required=rewrite_required,
        reason=_optional_text(decision_payload.get("reason")),
        approval_id=_optional_text(decision_payload.get("approval_id")),
        decided_by=(
            _optional_text(decision_payload.get("decided_by"))
            or _optional_text(decision_payload.get("actor_id"))
        ),
        modifications=modifications,
    )


def enrich_daily_approval_resume_context(
    approval_context: Mapping[str, Any],
    *,
    workflow_step_ids: Iterable[str] = (),
    workflow_buffer_keys: Iterable[str] = (),
) -> dict[str, Any]:
    context = dict(approval_context)
    route = build_daily_human_review_resume_route(
        context,
        workflow_step_ids=workflow_step_ids,
    )
    if route is None:
        return context
    route_payload = route.to_dict()
    buffer_updates = dict(context.get("buffer_updates") or {})
    route_updates = _declared_route_updates(
        route_payload,
        workflow_buffer_keys=tuple(str(key) for key in workflow_buffer_keys),
    )
    buffer_updates.update(route_updates)
    context["buffer_updates"] = buffer_updates
    resume_metadata = dict(context.get("resume_metadata") or {})
    resume_metadata["human_review_resume_route"] = route_payload
    resume_metadata["resume_next_step_id"] = route.next_step_id
    if route_updates:
        resume_metadata["allowed_patch_keys"] = _merged_patch_keys(
            resume_metadata.get("allowed_patch_keys"),
            route_updates.keys(),
        )
    context["resume_metadata"] = resume_metadata
    context["human_review_resume_route"] = route_payload
    return context


def normalize_daily_human_review_resume_route(value: Any) -> dict[str, Any] | None:
    if value is None:
        return None
    if isinstance(value, DailyHumanReviewResumeRoute):
        return value.to_dict()
    if not isinstance(value, Mapping):
        return None
    route = _text(value.get("route") or value.get("quality_route"))
    decision = _text(value.get("decision"))
    if route not in {"final", "blocked", "rewrite"}:
        if decision == "approved":
            route = "final"
        elif decision == "rejected":
            route = "blocked"
        elif decision == "needs_changes":
            route = "rewrite"
        else:
            return None
    return {
        "decision": decision or _decision_for_route(route),
        "route": route,
        "quality_route": _text(value.get("quality_route")) or route,
        "next_step_id": _text(value.get("next_step_id")) or _next_step_id(route, ()),
        "publication_allowed": bool(value.get("publication_allowed", route == "final")),
        "rewrite_required": bool(value.get("rewrite_required", route == "rewrite")),
        "reason": _optional_text(value.get("reason")),
        "approval_id": _optional_text(value.get("approval_id")),
        "decided_by": _optional_text(value.get("decided_by")),
        "modifications": _dict_value(value.get("modifications")),
    }


def _decision_payload(approval_context: Mapping[str, Any]) -> dict[str, Any]:
    payload = approval_context.get("decision_payload")
    if isinstance(payload, Mapping):
        return dict(payload)
    buffer_updates = approval_context.get("buffer_updates")
    if isinstance(buffer_updates, Mapping):
        for value in buffer_updates.values():
            if isinstance(value, Mapping) and value.get("decision"):
                return dict(value)
    return {}


def _declared_route_updates(
    route_payload: dict[str, Any],
    *,
    workflow_buffer_keys: tuple[str, ...],
) -> dict[str, Any]:
    route_updates = with_namespaced_aliases({"human_review_resume_route": route_payload})
    if not workflow_buffer_keys:
        return route_updates
    declared_keys = set(workflow_buffer_keys)
    return {
        key: value
        for key, value in route_updates.items()
        if key in declared_keys
    }


def _merged_patch_keys(
    current: Any,
    route_keys: Iterable[str],
) -> list[str]:
    if isinstance(current, (list, tuple, set)):
        patch_keys = {str(item) for item in current}
    elif current is None:
        patch_keys = set()
    else:
        patch_keys = {str(current)}
    patch_keys.update(str(key) for key in route_keys)
    return sorted(patch_keys)


def _next_step_id(route: str, step_ids: tuple[str, ...]) -> str:
    if route == "rewrite":
        if WRITER_STEP_ID in step_ids:
            return WRITER_STEP_ID
        if DRAFT_STEP_ID in step_ids:
            return DRAFT_STEP_ID
    if FINALIZE_STEP_ID in step_ids:
        return FINALIZE_STEP_ID
    return FINALIZE_STEP_ID


def _decision_for_route(route: str) -> str:
    if route == "blocked":
        return "rejected"
    if route == "rewrite":
        return "needs_changes"
    return "approved"


def _dict_value(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _text(value: Any) -> str:
    return str(value or "").strip().lower()


def _optional_text(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


__all__ = [
    "DailyHumanReviewResumeRoute",
    "build_daily_human_review_resume_route",
    "enrich_daily_approval_resume_context",
    "normalize_daily_human_review_resume_route",
]
