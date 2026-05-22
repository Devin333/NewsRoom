from __future__ import annotations

from dataclasses import replace
from typing import Any

from framework.workflow import DataBufferReadPermissionError, StepScopedDataBufferView
from business.foundation.models.report_output import BlockedReport, FinalReport, render_markdown
from business.layers.analysis.quality import EditorDecision, RewritePolicy
from business.boards.cross_board.workflows.daily_intelligence.evidence_step import quality_event
from business.boards.cross_board.workflows.daily_intelligence.quality_evaluation import evaluate_report_quality
from business.boards.cross_board.workflows.daily_intelligence.quality_result_builder import (
    human_review_request as build_human_review_request,
    quality_gate_metrics as build_quality_gate_metrics,
    quality_result as build_quality_result,
    quality_route as build_quality_route,
)
from business.boards.cross_board.workflows.daily_intelligence.quality_rewrite import rewrite_report_draft
from business.memory.intelligence_context import IntelligenceMemoryContext
from business.memory.intelligence_models import ClaimMemory, EventMemory
from business.memory.quality_memory_checks import QualityMemoryChecker


def quality_gate(buffer: StepScopedDataBufferView) -> dict[str, Any]:
    report_draft = buffer.read("report_draft")
    evidence_bundle = buffer.read("evidence_bundle")
    verified_findings = buffer.read("verified_findings")
    quality_events = list(buffer.read("quality_events"))
    memory_context = _read_memory_context(buffer)
    historian_context = _read_historian_context(buffer)
    historian_metadata = _historian_metadata(historian_context, report_draft, memory_context)
    memory_quality_result = _memory_quality_result(memory_context)
    memory_quality_result = _with_historian_quality_metadata(memory_quality_result, historian_metadata)
    if memory_quality_result["memory_available"]:
        quality_events.append(
            quality_event(
                "memory_quality_checked",
                passed=memory_quality_result["passed"],
                issue_count=len(memory_quality_result["issues"]),
            )
        )
    rewrite_policy = RewritePolicy()
    evaluation = evaluate_report_quality(
        report_draft,
        evidence_bundle,
        verified_findings,
        quality_events=quality_events,
        rewrite_policy=rewrite_policy,
        rewrite_attempts=0,
    )
    citation_check = evaluation["citation_check"]
    support_matrix = evaluation["support_matrix"]
    quality_summary = evaluation["quality_summary"]
    review = evaluation["review"]
    final_report_draft = report_draft
    rewritten_report_draft = None
    rewrite_attempts = 0

    if review.decision == EditorDecision.REWRITE_REQUIRED:
        quality_events.append(
            quality_event(
                "rewrite_started",
                rewrite_attempt=1,
                instruction_count=len(review.rewrite_instructions),
            )
        )
        rewritten_report_draft = rewrite_report_draft(
            report_draft,
            evidence_bundle,
            review,
        )
        rewrite_attempts = 1
        evaluation = evaluate_report_quality(
            rewritten_report_draft,
            evidence_bundle,
            verified_findings,
            quality_events=quality_events,
            rewrite_policy=rewrite_policy,
            rewrite_attempts=rewrite_attempts,
        )
        citation_check = evaluation["citation_check"]
        support_matrix = evaluation["support_matrix"]
        quality_summary = evaluation["quality_summary"]
        review = evaluation["review"]
        if review.decision == EditorDecision.PASS:
            quality_events.append(
                quality_event(
                    "rewrite_succeeded",
                    rewrite_attempt=rewrite_attempts,
                    quality_score=quality_summary.quality_score,
                )
            )
            final_report_draft = rewritten_report_draft
        else:
            quality_events.append(
                quality_event(
                    "rewrite_failed",
                    rewrite_attempt=rewrite_attempts,
                    decision=review.decision.value,
                    reason_count=len(review.reasons),
                )
            )

    human_review_request = build_human_review_request(
        evidence_bundle=evidence_bundle,
        review=review,
        quality_summary=quality_summary,
    )
    if _has_critical_memory_issue(memory_quality_result):
        review = replace(
            review,
            decision=EditorDecision.BLOCKED,
            reasons=[*review.reasons, "blocked by critical memory quality issue"],
            required_changes=[*review.required_changes, "resolve critical memory quality issue before publishing"],
            block_reasons=[*review.block_reasons, "critical memory quality issue"],
            final_notes="blocked by memory quality",
        )
        human_review_request = None
    human_review_required = human_review_request is not None
    if human_review_request:
        quality_events.append(
            quality_event(
                "human_review_requested",
                risk_level=human_review_request.risk_level,
                reason=human_review_request.reason,
            )
        )

    quality_gate_metrics = build_quality_gate_metrics(
        evidence_bundle=evidence_bundle,
        verified_findings=verified_findings,
        citation_check=citation_check,
        support_matrix=support_matrix,
        quality_summary=quality_summary,
        review=review,
        rewrite_attempts=rewrite_attempts,
        human_review_required=human_review_required,
    )
    quality_route = build_quality_route(
        review=review,
        rewrite_attempts=rewrite_attempts,
        human_review_required=human_review_required,
    )
    quality_result = build_quality_result(
        citation_check=citation_check,
        support_matrix=support_matrix,
        quality_summary=quality_summary,
        review=review,
        quality_gate_metrics=quality_gate_metrics,
        route=quality_route,
        rewrite_attempts=rewrite_attempts,
        human_review_required=human_review_required,
    )
    quality_result = _with_memory_quality_metadata(
        quality_result,
        memory_context=memory_context,
        memory_quality_result=memory_quality_result,
    )
    outputs: dict[str, Any] = {
        "citation_check_result": citation_check,
        "editor_review": review,
        "support_matrix": support_matrix,
        "report_quality_summary": quality_summary,
        "quality_events": quality_events,
        "quality_gate_metrics": quality_gate_metrics,
        "quality_result": quality_result,
        "quality_route": quality_route,
        "rewrite_policy": rewrite_policy,
        "rewrite_instructions": review.rewrite_instructions,
        "memory_quality_result": memory_quality_result,
    }
    if rewritten_report_draft is not None:
        outputs["rewritten_report_draft"] = rewritten_report_draft
    if human_review_request is not None:
        outputs["human_review_request"] = human_review_request
    if review.decision == EditorDecision.PASS:
        final_report = FinalReport(
            title=final_report_draft["title"],
            sections=final_report_draft["sections"],
            source_urls=sorted(evidence_bundle.source_urls),
            metadata={
                "evidence_bundle_id": evidence_bundle.bundle_id,
                "quality_score": quality_summary.quality_score,
                "accepted_claims_count": len(verified_findings.accepted_claims),
                "rejected_claims_count": len(verified_findings.rejected_claims),
                "uncertain_claims_count": len(verified_findings.uncertain_claims),
                "rewrite_attempts": rewrite_attempts,
                "memory_context": memory_context,
                "historian": historian_metadata,
                "memory_quality_result": memory_quality_result,
            },
        )
        outputs["final_report"] = final_report
        outputs["report_markdown"] = render_markdown(final_report)
    else:
        outputs["blocked_report"] = BlockedReport(
            title=final_report_draft.get("title", "Blocked Daily Intelligence Report"),
            reasons=review.reasons,
            draft=final_report_draft,
            metadata={
                "citation_check_result": citation_check.to_dict(),
                "citation_failure_categories": [
                    category.to_dict() for category in citation_check.failure_categories
                ],
                "editor_review": review.to_dict(),
                "quality_score": quality_summary.quality_score,
                "accepted_claims_count": quality_summary.accepted_claims_count,
                "rejected_claims_count": quality_summary.rejected_claims_count,
                "uncertain_claims_count": quality_summary.uncertain_claims_count,
                "unsupported_claims_count": quality_summary.unsupported_claims_count,
                "high_severity_unsupported_claims_count": (
                    quality_summary.high_severity_unsupported_claims_count
                ),
                "rewrite_attempts": rewrite_attempts,
                "human_review_required": human_review_required,
                "remediation": list(review.required_changes),
                "memory_context": memory_context,
                "historian": historian_metadata,
                "memory_quality_result": memory_quality_result,
            },
        )
    return outputs


def _read_memory_context(buffer: StepScopedDataBufferView) -> dict[str, Any] | None:
    try:
        if not buffer.exists("memory_context"):
            return None
        value = buffer.read("memory_context", required=False)
    except DataBufferReadPermissionError:
        return None
    return dict(value) if isinstance(value, dict) else None


def _read_historian_context(buffer: StepScopedDataBufferView) -> dict[str, Any] | None:
    try:
        if not buffer.exists("historian_context"):
            return None
        value = buffer.read("historian_context", required=False)
    except DataBufferReadPermissionError:
        return None
    return dict(value) if isinstance(value, dict) else None


def _memory_quality_result(memory_context: dict[str, Any] | None) -> dict[str, Any]:
    if not memory_context:
        return {
            "passed": True,
            "issues": [],
            "memory_available": False,
            "metadata": {"reason": "memory_context_missing"},
        }
    context = _memory_context_from_payload(memory_context)
    result = QualityMemoryChecker(_NoopMemoryQualityRepository()).check_report_context(context)
    payload = result.to_dict()
    metadata = dict(payload.get("metadata") or {})
    metadata.update(
        {
            "memory_available": bool((memory_context.get("metadata") or {}).get("memory_available", True)),
            "claim_count": len(context.claims),
            "event_count": len(context.events),
            "conflict_count": len(context.conflicts),
            "critical_issue_count": len(result.critical_issues()),
        }
    )
    payload["metadata"] = metadata
    payload["memory_available"] = metadata["memory_available"]
    return payload


def _historian_metadata(
    historian_context: dict[str, Any] | None,
    report_draft: dict[str, Any],
    memory_context: dict[str, Any] | None,
) -> dict[str, Any] | None:
    if historian_context:
        return dict(historian_context)
    report_metadata = report_draft.get("metadata") if isinstance(report_draft, dict) else None
    if isinstance(report_metadata, dict) and isinstance(report_metadata.get("historian"), dict):
        return dict(report_metadata["historian"])
    if memory_context and isinstance((memory_context.get("metadata") or {}).get("historian"), dict):
        return dict((memory_context.get("metadata") or {})["historian"])
    return None


def _with_historian_quality_metadata(
    memory_quality_result: dict[str, Any],
    historian_metadata: dict[str, Any] | None,
) -> dict[str, Any]:
    if not historian_metadata:
        return memory_quality_result
    payload = dict(memory_quality_result)
    metadata = dict(payload.get("metadata") or {})
    output = historian_metadata.get("output") if isinstance(historian_metadata.get("output"), dict) else {}
    repeated_claims = list(output.get("repeated_claims") or [])
    contradictions = list(output.get("contradictions") or [])
    metadata["historian"] = historian_metadata
    metadata["historian_repeated_claims"] = repeated_claims
    metadata["historian_contradictions"] = contradictions
    metadata["historian_repeated_claim_count"] = len(repeated_claims)
    metadata["historian_contradiction_count"] = len(contradictions)
    payload["metadata"] = metadata
    return payload


def _memory_context_from_payload(payload: dict[str, Any]) -> IntelligenceMemoryContext:
    query = str(payload.get("query") or payload.get("topic") or "")
    return IntelligenceMemoryContext(
        query=query,
        topic=str(payload["topic"]) if payload.get("topic") else None,
        claims=[_claim_from_payload(item) for item in _dict_items(payload.get("claims"))],
        events=[_event_from_payload(item) for item in _dict_items(payload.get("events"))],
        conflicts=[dict(item) for item in _dict_items(payload.get("conflicts"))],
        metadata=dict(payload.get("metadata") or {}),
    )


def _claim_from_payload(payload: dict[str, Any]) -> ClaimMemory:
    return ClaimMemory(
        claim_id=str(payload.get("claim_id") or payload.get("id") or "memory-claim"),
        run_id=str(payload.get("run_id") or "memory-context"),
        text=str(payload.get("text") or payload.get("claim") or ""),
        status=str(payload.get("status") or "active"),
        confidence=float(payload.get("confidence") or 0.5),
        evidence_ids=[str(item) for item in payload.get("evidence_ids") or [] if item is not None],
        contradicted_by=[str(item) for item in payload.get("contradicted_by") or [] if item is not None],
        metadata=dict(payload.get("metadata") or {}),
    )


def _event_from_payload(payload: dict[str, Any]) -> EventMemory:
    return EventMemory(
        event_id=str(payload.get("event_id") or payload.get("id") or "memory-event"),
        event_type=str(payload.get("event_type") or "general_news"),
        title=str(payload.get("title") or ""),
        summary=str(payload.get("summary") or ""),
        run_id=str(payload.get("run_id") or "memory-context"),
        topic=str(payload["topic"]) if payload.get("topic") else None,
        entity_ids=[str(item) for item in payload.get("entity_ids") or [] if item is not None],
        claim_ids=[str(item) for item in payload.get("claim_ids") or [] if item is not None],
        evidence_ids=[str(item) for item in payload.get("evidence_ids") or [] if item is not None],
        metadata=dict(payload.get("metadata") or {}),
    )


def _dict_items(value: Any) -> list[dict[str, Any]]:
    return [dict(item) for item in value or [] if isinstance(item, dict)]


def _has_critical_memory_issue(memory_quality_result: dict[str, Any]) -> bool:
    return any(
        isinstance(issue, dict) and issue.get("severity") == "critical"
        for issue in memory_quality_result.get("issues") or []
    )


class _NoopMemoryQualityRepository:
    def list_evidence_for_claim(self, claim_id: str):
        return []

    def find_similar_events(self, event: EventMemory, *, limit: int = 3):
        return []


def _with_memory_quality_metadata(
    quality_result: Any,
    *,
    memory_context: dict[str, Any] | None,
    memory_quality_result: dict[str, Any],
) -> Any:
    metadata = dict(getattr(quality_result, "metadata", {}) or {})
    metadata["memory_context"] = memory_context
    metadata["memory_quality_result"] = memory_quality_result
    return replace(quality_result, metadata=metadata)
