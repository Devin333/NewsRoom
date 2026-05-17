from __future__ import annotations

from typing import Any


VERIFICATION_STATUSES = frozenset({"pass", "needs_rewrite", "blocked"})
VERIFICATION_RISK_LEVELS = frozenset({"low", "medium", "high"})
EDITOR_DECISIONS = frozenset(
    {"pass", "rewrite_required", "human_review_required", "block"}
)


def validate_research_plan(payload: Any) -> dict[str, Any]:
    plan = _require_dict(payload, "research_plan")
    _require_keys(plan, ["topic", "sections", "constraints"], "research_plan")
    if not isinstance(plan["topic"], str) or not plan["topic"].strip():
        raise ValueError("research_plan.topic must be a non-empty string")
    if not isinstance(plan["sections"], list):
        raise ValueError("research_plan.sections must be a list")
    if not isinstance(plan["constraints"], dict):
        raise ValueError("research_plan.constraints must be an object")
    return dict(plan)


def validate_analysis_result(payload: Any) -> dict[str, Any]:
    result = _require_dict(payload, "analysis_result")
    _require_keys(
        result,
        ["findings", "trend_signals", "risk_notes", "uncertainty_notes"],
        "analysis_result",
    )
    for key in ("findings", "trend_signals", "risk_notes", "uncertainty_notes"):
        if not isinstance(result[key], list):
            raise ValueError(f"analysis_result.{key} must be a list")
    return dict(result)


def validate_report_draft(payload: Any) -> dict[str, Any]:
    draft = normalize_agent_report_draft(payload)
    _require_keys(draft, ["title", "sections", "metadata"], "report_draft")
    if not isinstance(draft["sections"], list):
        raise ValueError("report_draft.sections must be a list")
    for index, section in enumerate(draft["sections"]):
        context = f"report_draft.sections[{index}]"
        if not isinstance(section, dict):
            raise ValueError(f"{context} must be an object")
        _require_keys(section, ["title", "content", "sources"], context)
        if not isinstance(section["sources"], list):
            raise ValueError(f"{context}.sources must be a list")
    if not isinstance(draft["metadata"], dict):
        raise ValueError("report_draft.metadata must be an object")
    return draft


def validate_verification_result(payload: Any) -> dict[str, Any]:
    result = _require_dict(payload, "verification_result")
    _require_keys(
        result,
        [
            "status",
            "unsupported_claims",
            "missing_citations",
            "risk_level",
            "reasons",
        ],
        "verification_result",
    )
    if result["status"] not in VERIFICATION_STATUSES:
        raise ValueError("verification_result.status is not supported")
    if result["risk_level"] not in VERIFICATION_RISK_LEVELS:
        raise ValueError("verification_result.risk_level is not supported")
    for key in ("unsupported_claims", "missing_citations", "reasons"):
        if not isinstance(result[key], list):
            raise ValueError(f"verification_result.{key} must be a list")
    return dict(result)


def validate_editor_review(payload: Any) -> dict[str, Any]:
    review = _require_dict(payload, "editor_review")
    _require_keys(
        review,
        ["decision", "quality_score", "reasons", "rewrite_instructions"],
        "editor_review",
    )
    if review["decision"] not in EDITOR_DECISIONS:
        raise ValueError("editor_review.decision is not supported")
    if not isinstance(review["quality_score"], int | float):
        raise ValueError("editor_review.quality_score must be a number")
    for key in ("reasons", "rewrite_instructions"):
        if not isinstance(review[key], list):
            raise ValueError(f"editor_review.{key} must be a list")
    return dict(review)


def normalize_agent_report_draft(payload: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("report_draft must be an object")
    if "report_draft" in payload:
        nested = payload["report_draft"]
        if not isinstance(nested, dict):
            raise ValueError("report_draft must be an object")
        return dict(nested)
    return dict(payload)


def _require_dict(payload: Any, context: str) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError(f"{context} must be an object")
    return dict(payload)


def _require_keys(payload: dict[str, Any], keys: list[str], context: str) -> None:
    missing = [key for key in keys if key not in payload]
    if missing:
        raise ValueError(f"{context} missing required key(s): {', '.join(missing)}")
