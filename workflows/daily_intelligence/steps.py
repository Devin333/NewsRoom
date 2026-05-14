from __future__ import annotations

from typing import Any

from core.framework.workflow import ScopedDataBuffer
from domain.reports import BlockedReport, FinalReport, render_markdown
from domain.sources import SourceError, SourcePipelineEvent
from evidence import EvidenceBuilder, EvidenceBundle, VerifiedFindings
from quality import (
    CitationChecker,
    EditorDecision,
    EditorGate,
    HumanReviewRequest,
    QualityEvent,
    QualityGateMetrics,
    QualityResult,
    QualityScorer,
    RewritePolicy,
    SupportMatrixBuilder,
)
from sources.errors import classify_source_exception
from sources.processing import (
    build_source_coverage_report,
    build_source_freshness_report,
    build_source_governance_report,
    build_source_quality_summary_report,
    build_source_ranking_scores,
    build_source_traceability_report,
    deduplicate_with_result,
    normalize_item,
    rank_items,
)


class AllSourcesFailedError(RuntimeError):
    pass


def source_event(event_type: str, source_id: str | None = None, **metadata: Any) -> SourcePipelineEvent:
    return SourcePipelineEvent(
        event_type=event_type,
        source_id=source_id,
        metadata={key: value for key, value in metadata.items() if value is not None},
    )


def require_sources(buffer: ScopedDataBuffer) -> dict[str, Any]:
    raw_items = buffer.read("raw_items")
    if raw_items:
        return {"source_collection_status": "ready"}

    source_errors = buffer.read("source_errors")
    error_types = [
        error.error_type if hasattr(error, "error_type") else error.get("error_type", "unknown")
        for error in source_errors
    ]
    raise AllSourcesFailedError(
        "all_sources_failed: no source items collected from enabled sources "
        f"(errors: {', '.join(error_types)})"
    )


def normalize_sources(buffer: ScopedDataBuffer) -> dict[str, Any]:
    raw_items = buffer.read("raw_items")
    source_errors = list(buffer.read("source_errors"))
    normalized_items = []
    normalization_errors: list[SourceError] = []
    for raw_item in raw_items:
        try:
            normalized_items.append(normalize_item(raw_item))
        except Exception as exc:
            error = _processing_source_error(raw_item, exc, phase="normalize")
            normalization_errors.append(error)
            source_errors.append(error)
    source_events = list(buffer.read("source_events"))
    source_events.append(
        source_event("source_normalized", input_count=len(raw_items), output_count=len(normalized_items))
    )
    for error in normalization_errors:
        source_events.append(
            source_event(
                "source_normalization_failed",
                error.source_id,
                error_type=error.error_type,
                retryable=False,
            )
        )
    metrics = buffer.read("source_pipeline_metrics")
    metrics.normalized_items_count = len(normalized_items)
    for error in normalization_errors:
        metrics.record_error(error)
    return {
        "normalized_items": normalized_items,
        "source_errors": source_errors,
        "source_events": source_events,
        "source_pipeline_metrics": metrics,
    }


def deduplicate_sources(buffer: ScopedDataBuffer) -> dict[str, Any]:
    normalized_items = buffer.read("normalized_items")
    source_errors = list(buffer.read("source_errors"))
    try:
        dedup_result = deduplicate_with_result(normalized_items)
        deduplicated_items = dedup_result.kept_items
        source_duplicate_groups = [group.to_dict() for group in dedup_result.duplicate_groups]
        duplicate_count = len(dedup_result.dropped_items)
        dedup_errors: list[SourceError] = []
    except Exception as exc:
        error = _pipeline_processing_error(exc, phase="dedup")
        dedup_errors = [error]
        source_errors.append(error)
        deduplicated_items = []
        source_duplicate_groups = []
        duplicate_count = 0
    source_events = list(buffer.read("source_events"))
    metrics = buffer.read("source_pipeline_metrics")
    metrics.deduplicated_items_count = len(deduplicated_items)
    metrics.duplicate_count = duplicate_count
    for error in dedup_errors:
        metrics.record_error(error)
    source_events.append(
        source_event(
            "source_deduplicated",
            input_count=len(normalized_items),
            output_count=len(deduplicated_items),
            duplicate_count=metrics.duplicate_count,
            duplicate_group_count=len(source_duplicate_groups),
        )
    )
    for error in dedup_errors:
        source_events.append(source_event("source_dedup_failed", error_type=error.error_type, retryable=False))
    return {
        "deduplicated_items": deduplicated_items,
        "source_errors": source_errors,
        "source_duplicate_groups": source_duplicate_groups,
        "source_events": source_events,
        "source_pipeline_metrics": metrics,
    }


def rank_sources(buffer: ScopedDataBuffer) -> dict[str, Any]:
    request = buffer.read("request")
    deduplicated_items = buffer.read("deduplicated_items")
    source_errors = list(buffer.read("source_errors"))
    try:
        ranked_items = rank_items(deduplicated_items, topic=request["topic"])
        ranking_errors: list[SourceError] = []
    except Exception as exc:
        error = _pipeline_processing_error(exc, phase="rank")
        source_errors.append(error)
        ranking_errors = [error]
        ranked_items = []
    source_events = list(buffer.read("source_events"))
    source_events.append(
        source_event(
            "source_ranked",
            input_count=len(deduplicated_items),
            output_count=len(ranked_items),
            topic=request["topic"],
        )
    )
    for error in ranking_errors:
        source_events.append(source_event("source_ranking_failed", error_type=error.error_type, retryable=False))
    metrics = buffer.read("source_pipeline_metrics")
    metrics.ranked_items_count = len(ranked_items)
    for error in ranking_errors:
        metrics.record_error(error)
    source_quality_scores = [
        ranked.metadata["source_quality"]
        for ranked in ranked_items
        if "source_quality" in ranked.metadata
    ]
    source_ranking_scores = build_source_ranking_scores(ranked_items)
    source_freshness_report = build_source_freshness_report(ranked_items)
    source_traceability_report = build_source_traceability_report(ranked_items)
    source_quality_summary_report = build_source_quality_summary_report(source_quality_scores)
    return {
        "ranked_items": ranked_items,
        "source_errors": source_errors,
        "source_events": source_events,
        "source_pipeline_metrics": metrics,
        "source_coverage_report": build_source_coverage_report(
            metrics,
            source_errors=source_errors,
            skipped_sources=buffer.read("skipped_sources"),
            failed_sources=buffer.read("failed_sources"),
        ),
        "source_quality_scores": source_quality_scores,
        "source_quality_summary_report": source_quality_summary_report,
        "source_ranking_scores": source_ranking_scores,
        "source_freshness_report": source_freshness_report,
        "source_traceability_report": source_traceability_report,
        "source_governance_report": build_source_governance_report(
            source_quality_scores=source_quality_scores,
            source_selection_report=buffer.read("source_selection_report"),
        ),
    }


def build_evidence(buffer: ScopedDataBuffer) -> dict[str, Any]:
    build_result = EvidenceBuilder().build_with_scores(buffer.read("ranked_items"), bundle_id="daily")
    bundle = build_result.bundle
    if not bundle.items:
        raise RuntimeError("no valid evidence built from ranked sources")
    return {
        "evidence_bundle": bundle,
        "evidence_scores": build_result.evidence_scores,
        "candidate_claims": build_result.candidate_claims,
        "verified_findings": build_result.verified_findings,
        "quality_events": [
            _quality_event(
                "evidence_build_succeeded",
                evidence_items_count=len(bundle.items),
                evidence_scores_count=len(build_result.evidence_scores),
                candidate_claims_count=len(build_result.candidate_claims),
            ),
            _quality_event(
                "claim_verification_succeeded",
                accepted_claims_count=(
                    len(build_result.verified_findings.accepted_claims)
                    if build_result.verified_findings
                    else 0
                ),
                rejected_claims_count=(
                    len(build_result.verified_findings.rejected_claims)
                    if build_result.verified_findings
                    else 0
                ),
                uncertain_claims_count=(
                    len(build_result.verified_findings.uncertain_claims)
                    if build_result.verified_findings
                    else 0
                ),
            ),
        ],
    }


def quality_gate(buffer: ScopedDataBuffer) -> dict[str, Any]:
    report_draft = buffer.read("report_draft")
    evidence_bundle = buffer.read("evidence_bundle")
    verified_findings = buffer.read("verified_findings")
    quality_events = list(buffer.read("quality_events"))
    rewrite_policy = RewritePolicy()
    evaluation = _evaluate_report_quality(
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
            _quality_event(
                "rewrite_started",
                rewrite_attempt=1,
                instruction_count=len(review.rewrite_instructions),
            )
        )
        rewritten_report_draft = _rewrite_report_draft(
            report_draft,
            evidence_bundle,
            review,
        )
        rewrite_attempts = 1
        evaluation = _evaluate_report_quality(
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
                _quality_event(
                    "rewrite_succeeded",
                    rewrite_attempt=rewrite_attempts,
                    quality_score=quality_summary.quality_score,
                )
            )
            final_report_draft = rewritten_report_draft
        else:
            quality_events.append(
                _quality_event(
                    "rewrite_failed",
                    rewrite_attempt=rewrite_attempts,
                    decision=review.decision.value,
                    reason_count=len(review.reasons),
                )
            )

    human_review_request = _human_review_request(
        evidence_bundle=evidence_bundle,
        review=review,
        quality_summary=quality_summary,
    )
    human_review_required = human_review_request is not None
    if human_review_request:
        quality_events.append(
            _quality_event(
                "human_review_requested",
                risk_level=human_review_request.risk_level,
                reason=human_review_request.reason,
            )
        )

    quality_gate_metrics = _quality_gate_metrics(
        evidence_bundle=evidence_bundle,
        verified_findings=verified_findings,
        citation_check=citation_check,
        support_matrix=support_matrix,
        quality_summary=quality_summary,
        review=review,
        rewrite_attempts=rewrite_attempts,
        human_review_required=human_review_required,
    )
    quality_route = _quality_route(
        review=review,
        rewrite_attempts=rewrite_attempts,
        human_review_required=human_review_required,
    )
    quality_result = _quality_result(
        citation_check=citation_check,
        support_matrix=support_matrix,
        quality_summary=quality_summary,
        review=review,
        quality_gate_metrics=quality_gate_metrics,
        route=quality_route,
        rewrite_attempts=rewrite_attempts,
        human_review_required=human_review_required,
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
                "editor_review": review.to_dict(),
                "quality_score": quality_summary.quality_score,
                "rewrite_attempts": rewrite_attempts,
                "human_review_required": human_review_required,
            },
        )
    return outputs


def _evaluate_report_quality(
    report_draft: dict[str, Any],
    evidence_bundle: EvidenceBundle,
    verified_findings: VerifiedFindings,
    *,
    quality_events: list[QualityEvent],
    rewrite_policy: RewritePolicy,
    rewrite_attempts: int,
) -> dict[str, Any]:
    quality_events.append(
        _quality_event(
            "citation_check_started",
            evidence_items_count=len(evidence_bundle.items),
            rewrite_attempt=rewrite_attempts,
        )
    )
    citation_check = CitationChecker().check(report_draft, evidence_bundle, verified_findings)
    quality_events.append(
        _quality_event(
            "citation_check_succeeded" if citation_check.passed else "citation_check_failed",
            unsupported_urls_count=len(citation_check.unsupported_urls),
            unknown_urls_count=len(citation_check.unknown_urls),
            missing_section_sources_count=len(citation_check.missing_section_sources),
            unsupported_claims_count=len(citation_check.unsupported_claims),
            rejected_claim_usage_count=len(citation_check.rejected_claim_usage),
            citation_coverage_score=citation_check.citation_coverage_score,
            claim_support_score=citation_check.claim_support_score,
            rewrite_attempt=rewrite_attempts,
        )
    )
    support_matrix = SupportMatrixBuilder().build(report_draft, evidence_bundle)
    quality_summary = QualityScorer().score(
        report=report_draft,
        citation_check=citation_check,
        support_matrix=support_matrix,
    )
    quality_events.append(
        _quality_event(
            "editor_gate_started",
            quality_score=quality_summary.quality_score,
            rewrite_attempt=rewrite_attempts,
        )
    )
    review = EditorGate().review(
        citation_check,
        support_matrix,
        quality_summary,
        rewrite_policy=rewrite_policy,
        rewrite_attempts=rewrite_attempts,
    )
    quality_events.append(
        _quality_event(
            _editor_event_type(review.decision),
            decision=review.decision.value,
            quality_score=quality_summary.quality_score,
            reason_count=len(review.reasons),
            rewrite_attempt=rewrite_attempts,
        )
    )
    return {
        "citation_check": citation_check,
        "support_matrix": support_matrix,
        "quality_summary": quality_summary,
        "review": review,
    }


def _editor_event_type(decision: EditorDecision) -> str:
    if decision == EditorDecision.PASS:
        return "editor_gate_passed"
    if decision == EditorDecision.REWRITE_REQUIRED:
        return "editor_gate_rewrite_required"
    return "editor_gate_blocked"


def _rewrite_report_draft(
    report_draft: dict[str, Any],
    evidence_bundle: EvidenceBundle,
    review: Any,
) -> dict[str, Any]:
    sections = [dict(section) for section in report_draft.get("sections", [])]
    sections = _drop_duplicate_sections(sections)
    unsupported_claims = _unsupported_claim_texts(review.unsupported_claims)
    if unsupported_claims:
        sections = [
            rewritten
            for section in sections
            if (rewritten := _remove_unsupported_claims(section, unsupported_claims)) is not None
        ]
    evidence_by_url = {item.source_url: item for item in evidence_bundle.items}
    for section in sections:
        sources = section.get("sources") or section.get("source_urls") or []
        if sources:
            continue
        matched_urls = _matching_source_urls(str(section.get("content", "")), evidence_by_url)
        if matched_urls:
            section["sources"] = matched_urls
    rewritten = dict(report_draft)
    rewritten["sections"] = sections
    metadata = dict(rewritten.get("metadata") or {})
    metadata["rewrite"] = {
        "method": "rule",
        "instructions": list(review.rewrite_instructions),
        "preserve_evidence_boundary": True,
    }
    rewritten["metadata"] = metadata
    return rewritten


def _drop_duplicate_sections(sections: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen = set()
    deduplicated = []
    for section in sections:
        key = " ".join(str(section.get("content", "")).split()).casefold()
        if key and key in seen:
            continue
        if key:
            seen.add(key)
        deduplicated.append(section)
    return deduplicated


def _unsupported_claim_texts(unsupported_claims: list[str]) -> list[str]:
    texts = []
    for claim in unsupported_claims:
        if ": " in claim:
            texts.append(claim.split(": ", 1)[1])
        else:
            texts.append(claim)
    return texts


def _remove_unsupported_claims(
    section: dict[str, Any],
    unsupported_claims: list[str],
) -> dict[str, Any] | None:
    content = str(section.get("content", ""))
    for claim in unsupported_claims:
        content = content.replace(claim, "").strip()
    content = " ".join(content.split())
    if not content:
        return None
    updated = dict(section)
    updated["content"] = content
    return updated


def _matching_source_urls(content: str, evidence_by_url: dict[str, Any]) -> list[str]:
    matches = []
    for url, item in evidence_by_url.items():
        if _token_overlap(content, f"{item.title} {item.summary}") >= 0.25:
            matches.append(url)
    return sorted(matches)


def _token_overlap(left: str, right: str) -> float:
    import re

    left_tokens = {
        token
        for token in re.findall(r"[a-z0-9]+", left.casefold())
        if len(token) > 2
    }
    if not left_tokens:
        return 0.0
    right_tokens = {
        token
        for token in re.findall(r"[a-z0-9]+", right.casefold())
        if len(token) > 2
    }
    if not right_tokens:
        return 0.0
    return len(left_tokens & right_tokens) / len(left_tokens)


def _human_review_request(
    *,
    evidence_bundle: EvidenceBundle,
    review: Any,
    quality_summary: Any,
) -> HumanReviewRequest | None:
    if review.decision == EditorDecision.PASS and quality_summary.quality_score >= 0.8:
        return None
    risk_level = "critical" if review.decision == EditorDecision.BLOCKED else "medium"
    reason = "quality gate blocked" if review.decision == EditorDecision.BLOCKED else "quality gate rewrite required"
    return HumanReviewRequest(
        review_id=f"review-{evidence_bundle.bundle_id}",
        run_id=evidence_bundle.bundle_id,
        draft_id=f"draft-{evidence_bundle.bundle_id}",
        reason=reason,
        risk_level=risk_level,
        quality_artifact_refs={
            "citation_check_result": "citation_check_result.json",
            "editor_review": "editor_review.json",
            "report_quality_summary": "report_quality_summary.json",
        },
        metadata={
            "decision": review.decision.value,
            "quality_score": quality_summary.quality_score,
            "reason_count": len(review.reasons),
        },
    )


def _quality_gate_metrics(
    *,
    evidence_bundle: EvidenceBundle,
    verified_findings: VerifiedFindings,
    citation_check: Any,
    support_matrix: Any,
    quality_summary: Any,
    review: Any,
    rewrite_attempts: int,
    human_review_required: bool,
) -> QualityGateMetrics:
    return QualityGateMetrics(
        evidence_items_count=len(evidence_bundle.items),
        unsupported_urls_count=len(citation_check.unsupported_urls),
        missing_section_sources_count=len(citation_check.missing_section_sources),
        unsupported_sections_count=len(support_matrix.unsupported_sections),
        blocked=review.decision != EditorDecision.PASS,
        decision=review.decision.value,
        citation_coverage_score=citation_check.citation_coverage_score,
        support_coverage=quality_summary.support_coverage,
        quality_score=quality_summary.quality_score,
        accepted_claims_count=len(verified_findings.accepted_claims),
        rejected_claims_count=len(verified_findings.rejected_claims),
        uncertain_claims_count=len(verified_findings.uncertain_claims),
        unsupported_claims_count=len(citation_check.unsupported_claims),
        rejected_claim_usage_count=len(citation_check.rejected_claim_usage),
        claim_support_score=citation_check.claim_support_score,
        section_source_coverage_score=citation_check.section_source_coverage_score,
        rewrite_attempts=rewrite_attempts,
        rewrite_required=review.decision == EditorDecision.REWRITE_REQUIRED,
        human_review_required=human_review_required,
    )


def _quality_route(
    *,
    review: Any,
    rewrite_attempts: int,
    human_review_required: bool,
) -> str:
    if human_review_required:
        return "human_review"
    if review.decision == EditorDecision.BLOCKED:
        return "blocked"
    if rewrite_attempts > 0 or review.decision == EditorDecision.REWRITE_REQUIRED:
        return "rewrite"
    return "final"


def _quality_route_history(
    *,
    route: str,
    review: Any,
    rewrite_attempts: int,
    human_review_required: bool,
) -> list[str]:
    history = []
    if rewrite_attempts > 0:
        history.append("rewrite")
    if review.decision == EditorDecision.BLOCKED:
        history.append("blocked")
    if human_review_required:
        history.append("human_review")
    if not history:
        history.append(route)
    return history


def _quality_result(
    *,
    citation_check: Any,
    support_matrix: Any,
    quality_summary: Any,
    review: Any,
    quality_gate_metrics: Any,
    route: str,
    rewrite_attempts: int,
    human_review_required: bool,
) -> QualityResult:
    return QualityResult(
        decision=review.decision.value,
        passed=review.decision == EditorDecision.PASS,
        route=route,
        blocked=review.decision != EditorDecision.PASS,
        quality_score=quality_summary.quality_score,
        citation_coverage_score=citation_check.citation_coverage_score,
        claim_support_score=citation_check.claim_support_score,
        section_source_coverage_score=citation_check.section_source_coverage_score,
        support_coverage=quality_summary.support_coverage,
        evidence_alignment_score=quality_summary.evidence_alignment_score,
        rewrite_attempts=rewrite_attempts,
        rewrite_required=review.decision == EditorDecision.REWRITE_REQUIRED,
        human_review_required=human_review_required,
        route_history=_quality_route_history(
            route=route,
            review=review,
            rewrite_attempts=rewrite_attempts,
            human_review_required=human_review_required,
        ),
        reasons=review.reasons,
        artifact_refs={
            "citation_check_result": "citation_check_result.json",
            "editor_review": "editor_review.json",
            "support_matrix": "support_matrix.json",
            "report_quality_summary": "report_quality_summary.json",
            "quality_gate_metrics": "quality_gate_metrics.json",
            "quality_events": "quality_events.json",
        },
        citation_check_result=citation_check,
        editor_review=review,
        support_matrix=support_matrix,
        report_quality_summary=quality_summary,
        quality_gate_metrics=quality_gate_metrics,
        metadata={
            "source": "daily.quality_gate",
            "failure_route": route if review.decision != EditorDecision.PASS else None,
        },
    )


def _processing_source_error(raw_item: Any, exc: Exception, *, phase: str) -> SourceError:
    classification = classify_source_exception(exc, phase=phase)
    source_id = str(getattr(raw_item, "source_id", "source_pipeline") or "source_pipeline")
    return SourceError(
        source_id=source_id,
        source_name=getattr(raw_item, "source_name", None),
        error_type=classification.error_type,
        error_message=str(exc),
        url=getattr(raw_item, "url", None),
        retryable=classification.retryable,
        metadata={
            "phase": phase,
            "source_item_id": getattr(raw_item, "source_item_id", None),
            "retryable": classification.retryable,
            "source_health_affecting": classification.source_health_affecting,
            "workflow_blocking": classification.workflow_blocking,
            "original_exception_type": type(exc).__name__,
        },
    )


def _pipeline_processing_error(exc: Exception, *, phase: str) -> SourceError:
    classification = classify_source_exception(exc, phase=phase)
    return SourceError(
        source_id="source_pipeline",
        source_name="Source Pipeline",
        error_type=classification.error_type,
        error_message=str(exc),
        retryable=classification.retryable,
        metadata={
            "phase": phase,
            "retryable": classification.retryable,
            "source_health_affecting": classification.source_health_affecting,
            "workflow_blocking": classification.workflow_blocking,
            "original_exception_type": type(exc).__name__,
        },
    )


def _quality_event(event_type: str, **metadata: Any) -> QualityEvent:
    return QualityEvent(
        event_type=event_type,
        metadata={key: value for key, value in metadata.items() if value is not None},
    )


