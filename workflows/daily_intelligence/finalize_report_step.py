from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from typing import Any

from core.framework.workflow import ScopedDataBuffer
from domain.reports import BlockedReport, FinalReport, render_markdown
from workflows.daily_intelligence.evidence_step import quality_event


PUBLISH_ROUTE = "publish"
BLOCKED_ROUTE = "blocked"
HUMAN_REVIEW_ROUTE = "human_review"

PASS_DECISION = "pass"
REWRITE_REQUIRED_DECISION = "rewrite_required"
HUMAN_REVIEW_REQUIRED_DECISION = "human_review_required"
BLOCK_DECISION = "block"

_DECISION_ALIASES = {
    "blocked": BLOCK_DECISION,
    "human_review": HUMAN_REVIEW_REQUIRED_DECISION,
    "human_review_required": HUMAN_REVIEW_REQUIRED_DECISION,
    "pass": PASS_DECISION,
    "publish": PASS_DECISION,
    "rewrite": REWRITE_REQUIRED_DECISION,
    "rewrite_required": REWRITE_REQUIRED_DECISION,
}


def finalize_report(buffer: ScopedDataBuffer) -> dict[str, Any]:
    """Assemble the agentic Daily report outputs without calling an LLM."""

    request = buffer.read("request")
    report_draft = _normalize_report_draft(buffer.read("report_draft"))
    edited_report_draft = _read_optional_draft(buffer, "edited_report_draft")
    editor_decision = normalize_editor_decision(buffer.read("editor_review"))
    verification_result = _to_plain_dict(buffer.read("verification_result"))
    citation_check_result = _to_plain_dict(buffer.read("citation_check_result"))
    support_matrix = _to_plain_dict(buffer.read("support_matrix"))
    evidence_bundle = buffer.read("evidence_bundle")
    verified_findings = buffer.read("verified_findings")
    quality_events = list(buffer.read("quality_events"))

    decision = editor_decision["decision"]
    rewrite_instructions = list(editor_decision["rewrite_instructions"])
    quality_score = editor_decision["quality_score"]

    if decision == PASS_DECISION:
        return _publish_outputs(
            request=request,
            final_draft=report_draft,
            evidence_bundle=evidence_bundle,
            verified_findings=verified_findings,
            editor_decision=editor_decision,
            verification_result=verification_result,
            citation_check_result=citation_check_result,
            support_matrix=support_matrix,
            quality_events=[
                *quality_events,
                quality_event(
                    "finalize_report_published",
                    decision=decision,
                    quality_score=quality_score,
                ),
            ],
            rewrite_attempts=0,
            rewrite_instructions=rewrite_instructions,
        )

    if decision == REWRITE_REQUIRED_DECISION:
        if edited_report_draft is not None:
            invalid_sources = _sources_outside_evidence(
                edited_report_draft,
                evidence_bundle,
            )
            if not invalid_sources:
                return _publish_outputs(
                    request=request,
                    final_draft=edited_report_draft,
                    evidence_bundle=evidence_bundle,
                    verified_findings=verified_findings,
                    editor_decision=editor_decision,
                    verification_result=verification_result,
                    citation_check_result=citation_check_result,
                    support_matrix=support_matrix,
                    quality_events=[
                        *quality_events,
                        quality_event(
                            "finalize_report_published_after_edit",
                            decision=decision,
                            quality_score=quality_score,
                        ),
                    ],
                    rewrite_attempts=1,
                    rewrite_instructions=rewrite_instructions,
                )
            editor_decision = _append_editor_reason(
                editor_decision,
                "edited report draft cites sources outside evidence bundle: "
                + ", ".join(invalid_sources),
            )
            quality_events.append(
                quality_event(
                    "finalize_report_rewrite_source_boundary_failed",
                    invalid_sources=invalid_sources,
                    quality_score=quality_score,
                )
            )
        else:
            quality_events.append(
                quality_event(
                    "finalize_report_rewrite_missing_edit",
                    quality_score=quality_score,
                )
            )

    if decision == HUMAN_REVIEW_REQUIRED_DECISION:
        quality_events.append(
            quality_event(
                "finalize_report_human_review_requested",
                quality_score=quality_score,
                reason_count=len(editor_decision["reasons"]),
            )
        )
        return _blocked_outputs(
            request=request,
            report_draft=report_draft,
            evidence_bundle=evidence_bundle,
            editor_decision=editor_decision,
        verification_result=verification_result,
        citation_check_result=citation_check_result,
        support_matrix=support_matrix,
        verified_findings=verified_findings,
        quality_events=quality_events,
        route=HUMAN_REVIEW_ROUTE,
        rewrite_attempts=0,
        human_review_required=True,
            human_review_request=_human_review_request(
                request=request,
                report_draft=report_draft,
                evidence_bundle=evidence_bundle,
                editor_decision=editor_decision,
                verification_result=verification_result,
            ),
        )

    quality_events.append(
        quality_event(
            "finalize_report_blocked",
            decision=decision,
            quality_score=quality_score,
            reason_count=len(editor_decision["reasons"]),
        )
    )
    return _blocked_outputs(
        request=request,
        report_draft=report_draft,
        evidence_bundle=evidence_bundle,
        editor_decision=editor_decision,
        verification_result=verification_result,
        citation_check_result=citation_check_result,
        support_matrix=support_matrix,
        verified_findings=verified_findings,
        quality_events=quality_events,
        route=BLOCKED_ROUTE,
        rewrite_attempts=0,
        human_review_required=False,
    )


def normalize_editor_decision(editor_review: Any) -> dict[str, Any]:
    review = _unwrap_editor_review(editor_review)
    raw_decision = _field_value(review, "decision")
    decision = _normalize_decision(raw_decision)
    reasons = _string_list(_field_value(review, "reasons", default=[]))
    rewrite_instructions = _string_list(
        _field_value(
            review,
            "rewrite_instructions",
            default=_field_value(review, "required_changes", default=[]),
        )
    )
    quality_score = _float_value(_field_value(review, "quality_score"), default=0.0)
    return {
        "decision": decision,
        "quality_score": quality_score,
        "reasons": reasons,
        "rewrite_instructions": rewrite_instructions,
        "raw": _to_plain_dict(editor_review),
    }


def _append_editor_reason(editor_decision: dict[str, Any], reason: str) -> dict[str, Any]:
    next_decision = dict(editor_decision)
    reasons = list(next_decision.get("reasons") or [])
    reasons.append(reason)
    next_decision["reasons"] = reasons
    return next_decision


def _publish_outputs(
    *,
    request: Any,
    final_draft: dict[str, Any],
    evidence_bundle: Any,
    verified_findings: Any,
    editor_decision: dict[str, Any],
    verification_result: dict[str, Any],
    citation_check_result: dict[str, Any],
    support_matrix: dict[str, Any],
    quality_events: list[Any],
    rewrite_attempts: int,
    rewrite_instructions: list[str],
) -> dict[str, Any]:
    final_report = _final_report(
        request=request,
        draft=final_draft,
        evidence_bundle=evidence_bundle,
        verified_findings=verified_findings,
        editor_decision=editor_decision,
        rewrite_attempts=rewrite_attempts,
    )
    report_quality_summary = _report_quality_summary(
        editor_decision=editor_decision,
        verification_result=verification_result,
        citation_check_result=citation_check_result,
        support_matrix=support_matrix,
        route=PUBLISH_ROUTE,
    )
    quality_gate_metrics = _quality_gate_metrics(
        evidence_bundle=evidence_bundle,
        verified_findings=verified_findings,
        editor_decision=editor_decision,
        verification_result=verification_result,
        citation_check_result=citation_check_result,
        support_matrix=support_matrix,
        route=PUBLISH_ROUTE,
        rewrite_attempts=rewrite_attempts,
        human_review_required=False,
    )
    quality_result = _quality_result(
        editor_decision=editor_decision,
        route=PUBLISH_ROUTE,
        rewrite_attempts=rewrite_attempts,
        human_review_required=False,
        quality_gate_metrics=quality_gate_metrics,
        citation_check_result=citation_check_result,
    )
    return {
        "report_quality_summary": report_quality_summary,
        "quality_events": quality_events,
        "quality_gate_metrics": quality_gate_metrics,
        "quality_result": quality_result,
        "quality_route": {"route": PUBLISH_ROUTE},
        "rewrite_instructions": rewrite_instructions,
        "final_report": final_report,
        "report_markdown": render_markdown(final_report),
    }


def _blocked_outputs(
    *,
    request: Any,
    report_draft: dict[str, Any],
    evidence_bundle: Any,
    editor_decision: dict[str, Any],
    verification_result: dict[str, Any],
    citation_check_result: dict[str, Any],
    support_matrix: dict[str, Any],
    verified_findings: Any,
    quality_events: list[Any],
    route: str,
    rewrite_attempts: int,
    human_review_required: bool,
    human_review_request: dict[str, Any] | None = None,
) -> dict[str, Any]:
    report_quality_summary = _report_quality_summary(
        editor_decision=editor_decision,
        verification_result=verification_result,
        citation_check_result=citation_check_result,
        support_matrix=support_matrix,
        route=route,
    )
    quality_gate_metrics = _quality_gate_metrics(
        evidence_bundle=evidence_bundle,
        verified_findings=verified_findings,
        editor_decision=editor_decision,
        verification_result=verification_result,
        citation_check_result=citation_check_result,
        support_matrix=support_matrix,
        route=route,
        rewrite_attempts=rewrite_attempts,
        human_review_required=human_review_required,
    )
    quality_result = _quality_result(
        editor_decision=editor_decision,
        route=route,
        rewrite_attempts=rewrite_attempts,
        human_review_required=human_review_required,
        quality_gate_metrics=quality_gate_metrics,
        citation_check_result=citation_check_result,
    )
    reasons = list(editor_decision["reasons"]) or [_default_block_reason(route)]
    blocked_report = BlockedReport(
        title=report_draft.get("title") or _request_title(request),
        reasons=reasons,
        draft=report_draft,
        metadata={
            "evidence_bundle_id": _field_value(evidence_bundle, "bundle_id"),
            "quality_score": editor_decision["quality_score"],
            "quality_route": route,
            "verification_result": verification_result,
            "citation_check_result": citation_check_result,
            "citation_failure_categories": _list_value(
                citation_check_result.get("failure_categories")
            ),
            "support_matrix": support_matrix,
            "rewrite_attempts": rewrite_attempts,
            "human_review_required": human_review_required,
        },
    )
    outputs: dict[str, Any] = {
        "report_quality_summary": report_quality_summary,
        "quality_events": quality_events,
        "quality_gate_metrics": quality_gate_metrics,
        "quality_result": quality_result,
        "quality_route": {"route": route},
        "rewrite_instructions": list(editor_decision["rewrite_instructions"]),
        "blocked_report": blocked_report,
    }
    if human_review_request is not None:
        outputs["human_review_request"] = human_review_request
    return outputs


def _final_report(
    *,
    request: Any,
    draft: dict[str, Any],
    evidence_bundle: Any,
    verified_findings: Any,
    editor_decision: dict[str, Any],
    rewrite_attempts: int,
) -> FinalReport:
    source_urls = _source_urls_from_draft(draft)
    if not source_urls:
        source_urls = _source_urls_from_evidence(evidence_bundle)
    metadata = dict(draft.get("metadata") or {})
    metadata.update(
        {
            "evidence_bundle_id": _field_value(evidence_bundle, "bundle_id"),
            "quality_score": editor_decision["quality_score"],
            "accepted_claims_count": _collection_count(verified_findings, "accepted_claims"),
            "rejected_claims_count": _collection_count(verified_findings, "rejected_claims"),
            "uncertain_claims_count": _collection_count(verified_findings, "uncertain_claims"),
            "rewrite_attempts": rewrite_attempts,
            "request_topic": _field_value(request, "topic"),
        }
    )
    return FinalReport(
        title=draft.get("title") or _request_title(request),
        sections=list(draft["sections"]),
        source_urls=sorted(source_urls),
        metadata=metadata,
    )


def _report_quality_summary(
    *,
    editor_decision: dict[str, Any],
    verification_result: dict[str, Any],
    citation_check_result: dict[str, Any],
    support_matrix: dict[str, Any],
    route: str,
) -> dict[str, Any]:
    return {
        "quality_score": editor_decision["quality_score"],
        "decision": editor_decision["decision"],
        "route": route,
        "verification_status": verification_result.get("status"),
        "risk_level": verification_result.get("risk_level"),
        "citation_passed": citation_check_result.get("passed"),
        "support_coverage": _float_value(support_matrix.get("coverage_ratio"), default=None),
        "accepted_claims_count": len(_list_value((support_matrix.get("accepted_claim_ids")))),
        "rejected_claims_count": len(_list_value((support_matrix.get("rejected_claim_ids")))),
        "uncertain_claims_count": len(_list_value((support_matrix.get("uncertain_claim_ids")))),
        "unsupported_claims_count": len(_list_value((support_matrix.get("unsupported_claims")))),
        "high_severity_unsupported_claims_count": len(
            _list_value(support_matrix.get("high_severity_unsupported_claims"))
        ),
        "reason_count": len(editor_decision["reasons"]),
    }


def _quality_gate_metrics(
    *,
    evidence_bundle: Any,
    verified_findings: Any,
    editor_decision: dict[str, Any],
    verification_result: dict[str, Any],
    citation_check_result: dict[str, Any],
    support_matrix: dict[str, Any],
    route: str,
    rewrite_attempts: int,
    human_review_required: bool,
) -> dict[str, Any]:
    unsupported_claims = _list_value(
        verification_result.get("unsupported_claims")
        or citation_check_result.get("unsupported_claims")
    )
    missing_citations = _list_value(
        verification_result.get("missing_citations")
        or citation_check_result.get("missing_section_sources")
    )
    unsupported_sections = _list_value(support_matrix.get("unsupported_sections"))
    return {
        "evidence_items_count": _evidence_item_count(evidence_bundle),
        "accepted_claims_count": _collection_count(verified_findings, "accepted_claims"),
        "rejected_claims_count": _collection_count(verified_findings, "rejected_claims"),
        "uncertain_claims_count": _collection_count(verified_findings, "uncertain_claims"),
        "unsupported_claims_count": len(unsupported_claims),
        "missing_citations_count": len(missing_citations),
        "unknown_urls_count": len(_list_value(citation_check_result.get("unknown_urls"))),
        "unsupported_evidence_ids_count": len(
            _list_value(citation_check_result.get("unsupported_evidence_ids"))
        ),
        "citation_failure_category_count": len(
            _list_value(citation_check_result.get("failure_categories"))
        ),
        "citation_failure_categories": [
            str(category.get("code"))
            for category in _list_value(citation_check_result.get("failure_categories"))
            if isinstance(category, Mapping) and category.get("code")
        ],
        "unsupported_sections_count": len(unsupported_sections),
        "blocked": route != PUBLISH_ROUTE,
        "decision": editor_decision["decision"],
        "route": route,
        "risk_level": verification_result.get("risk_level"),
        "quality_score": editor_decision["quality_score"],
        "rewrite_attempts": rewrite_attempts,
        "rewrite_required": editor_decision["decision"] == REWRITE_REQUIRED_DECISION,
        "human_review_required": human_review_required,
    }


def _quality_result(
    *,
    editor_decision: dict[str, Any],
    route: str,
    rewrite_attempts: int,
    human_review_required: bool,
    quality_gate_metrics: dict[str, Any],
    citation_check_result: dict[str, Any],
) -> dict[str, Any]:
    passed = route == PUBLISH_ROUTE
    return {
        "decision": editor_decision["decision"],
        "passed": passed,
        "route": route,
        "blocked": not passed,
        "quality_score": editor_decision["quality_score"],
        "rewrite_attempts": rewrite_attempts,
        "rewrite_required": editor_decision["decision"] == REWRITE_REQUIRED_DECISION,
        "human_review_required": human_review_required,
        "route_history": _route_history(
            route=route,
            decision=editor_decision["decision"],
            rewrite_attempts=rewrite_attempts,
            human_review_required=human_review_required,
        ),
        "reasons": list(editor_decision["reasons"]),
        "artifact_refs": {
            "editor_review": "editor_review.json",
            "report_quality_summary": "report_quality_summary.json",
            "quality_gate_metrics": "quality_gate_metrics.json",
            "quality_events": "quality_events.json",
        },
        "quality_gate_metrics": dict(quality_gate_metrics),
        "metadata": {
            "source": "daily.finalize_report",
            "citation_failure_categories": _list_value(
                citation_check_result.get("failure_categories")
            ),
            "remediation": list(editor_decision["rewrite_instructions"])
            or [
                "human reviewer must approve, reject, or request rewrite"
                if human_review_required
                else None
            ],
        },
    }


def _human_review_request(
    *,
    request: Any,
    report_draft: dict[str, Any],
    evidence_bundle: Any,
    editor_decision: dict[str, Any],
    verification_result: dict[str, Any],
) -> dict[str, Any]:
    bundle_id = _field_value(evidence_bundle, "bundle_id") or "daily"
    review_id = f"review-{bundle_id}"
    return {
        "review_id": review_id,
        "run_id": _field_value(request, "run_id") or bundle_id,
        "draft_id": f"draft-{bundle_id}",
        "reason": _first_or_default(
            editor_decision["reasons"],
            "editor requested human review before publication",
        ),
        "risk_level": verification_result.get("risk_level") or "medium",
        "status": "pending",
        "title": report_draft.get("title") or _request_title(request),
        "quality_score": editor_decision["quality_score"],
        "reasons": list(editor_decision["reasons"]),
        "rewrite_instructions": list(editor_decision["rewrite_instructions"]),
        "quality_artifact_refs": {
            "editor_review": "editor_review.json",
            "quality_result": "quality_result.json",
            "quality_gate_metrics": "quality_gate_metrics.json",
        },
        "metadata": {
            "decision": editor_decision["decision"],
            "evidence_bundle_id": bundle_id,
        },
    }


def _read_optional_draft(buffer: ScopedDataBuffer, key: str) -> dict[str, Any] | None:
    if not buffer.exists(key):
        return None
    value = buffer.read(key)
    if value is None:
        return None
    return _normalize_report_draft(value)


def _normalize_report_draft(payload: Any) -> dict[str, Any]:
    if isinstance(payload, Mapping) and "report_draft" in payload and "sections" not in payload:
        payload = payload["report_draft"]
    if not isinstance(payload, Mapping):
        raise ValueError("report draft must be an object")
    draft = dict(payload)
    sections = draft.get("sections")
    if not isinstance(sections, list):
        raise ValueError("report draft sections must be a list")
    normalized_sections = []
    for index, section in enumerate(sections):
        if not isinstance(section, Mapping):
            raise ValueError(f"report draft section {index} must be an object")
        section_payload = dict(section)
        section_payload["title"] = str(section_payload.get("title") or f"Section {index + 1}")
        section_payload["content"] = str(section_payload.get("content") or "")
        section_payload["sources"] = _string_list(
            section_payload.get("sources") or section_payload.get("source_urls") or []
        )
        section_payload["section_id"] = str(
            section_payload.get("section_id")
            or section_payload.get("id")
            or f"section_{index + 1}"
        )
        section_payload["evidence_ids"] = _string_list(section_payload.get("evidence_ids") or [])
        section_payload["claim_grounding"] = _normalize_claim_grounding(
            section_payload.get("claim_grounding") or []
        )
        normalized_sections.append(section_payload)
    draft["title"] = str(draft.get("title") or "Daily Intelligence Report")
    draft["sections"] = normalized_sections
    metadata = draft.get("metadata")
    draft["metadata"] = dict(metadata) if isinstance(metadata, Mapping) else {}
    return draft


def _unwrap_editor_review(editor_review: Any) -> Any:
    if (
        isinstance(editor_review, Mapping)
        and "editor_review" in editor_review
        and "decision" not in editor_review
    ):
        return editor_review["editor_review"]
    return editor_review


def _normalize_decision(value: Any) -> str:
    if hasattr(value, "value"):
        value = value.value
    normalized = str(value or "").strip().lower()
    decision = _DECISION_ALIASES.get(normalized)
    if decision is None:
        allowed = ", ".join(sorted(set(_DECISION_ALIASES.values())))
        raise ValueError(f"unsupported editor decision: {value!r}; expected one of {allowed}")
    return decision


def _route_history(
    *,
    route: str,
    decision: str,
    rewrite_attempts: int,
    human_review_required: bool,
) -> list[str]:
    history: list[str] = []
    if rewrite_attempts > 0 or decision == REWRITE_REQUIRED_DECISION:
        history.append("rewrite")
    if human_review_required:
        history.append(HUMAN_REVIEW_ROUTE)
    if route == BLOCKED_ROUTE:
        history.append(BLOCKED_ROUTE)
    if route == PUBLISH_ROUTE:
        history.append(PUBLISH_ROUTE)
    return history or [route]


def _source_urls_from_draft(draft: dict[str, Any]) -> set[str]:
    urls: set[str] = set()
    for section in draft.get("sections") or []:
        if isinstance(section, Mapping):
            urls.update(_string_list(section.get("sources") or section.get("source_urls") or []))
    return urls


def _source_urls_from_evidence(evidence_bundle: Any) -> set[str]:
    urls = set(_string_list(_field_value(evidence_bundle, "source_urls", default=[])))
    source_map = _field_value(evidence_bundle, "source_map", default={})
    if isinstance(source_map, Mapping):
        urls.update(str(url) for url in source_map if url)
    items = _field_value(evidence_bundle, "items", default=[])
    for item in _list_value(items):
        urls.update(_string_list(_field_value(item, "source_urls", default=[])))
        source_url = _field_value(item, "source_url")
        if source_url:
            urls.add(str(source_url))
    return urls


def _sources_outside_evidence(
    draft: dict[str, Any],
    evidence_bundle: Any,
) -> list[str]:
    allowed_sources = _source_urls_from_evidence(evidence_bundle)
    draft_sources = _source_urls_from_draft(draft)
    return sorted(source for source in draft_sources if source not in allowed_sources)


def _evidence_item_count(evidence_bundle: Any) -> int:
    item_count = _field_value(evidence_bundle, "item_count")
    if item_count is not None:
        try:
            return int(item_count)
        except (TypeError, ValueError):
            return 0
    return len(_list_value(_field_value(evidence_bundle, "items", default=[])))


def _collection_count(value: Any, field_name: str) -> int:
    if value is None:
        return 0
    return len(_list_value(_field_value(value, field_name, default=[])))


def _field_value(value: Any, field_name: str, default: Any = None) -> Any:
    if isinstance(value, Mapping):
        return value.get(field_name, default)
    if hasattr(value, field_name):
        return getattr(value, field_name)
    return default


def _to_plain_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return deepcopy(dict(value))
    if hasattr(value, "to_dict"):
        result = value.to_dict()
        return deepcopy(result) if isinstance(result, dict) else {"value": result}
    if value is None:
        return {}
    return {"value": deepcopy(value)}


def _list_value(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return list(value)
    if isinstance(value, tuple | set):
        return list(value)
    return [value]


def _string_list(value: Any) -> list[str]:
    result = []
    for item in _list_value(value):
        if item is None:
            continue
        text = str(item)
        if text:
            result.append(text)
    return result


def _normalize_claim_grounding(value: Any) -> list[dict[str, Any]]:
    grounded_claims: list[dict[str, Any]] = []
    for item in _list_value(value):
        if not isinstance(item, Mapping):
            continue
        grounded_claims.append(
            {
                "claim_id": str(item.get("claim_id") or ""),
                "text": str(item.get("text") or item.get("claim") or ""),
                "evidence_ids": _string_list(item.get("evidence_ids") or []),
                "source_urls": _string_list(item.get("source_urls") or item.get("sources") or []),
            }
        )
    return grounded_claims


def _float_value(value: Any, *, default: float | None) -> float | None:
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _request_title(request: Any) -> str:
    topic = _field_value(request, "topic")
    if topic:
        return f"Daily Intelligence: {topic}"
    return "Daily Intelligence Report"


def _first_or_default(values: list[str], default: str) -> str:
    return values[0] if values else default


def _default_block_reason(route: str) -> str:
    if route == HUMAN_REVIEW_ROUTE:
        return "human review required before publication"
    return "editor blocked final publication"
