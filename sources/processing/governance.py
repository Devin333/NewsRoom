from __future__ import annotations

from typing import Any

from domain.sources import SourceGovernanceFinding, SourceGovernanceReport


COMMUNITY_SOURCE_TYPES = {"hackernews", "reddit"}
COMMUNITY_CATEGORIES = {"community", "developer_community", "social"}


def build_source_governance_report(
    *,
    source_quality_scores: list[dict[str, Any]],
    source_selection_report: Any | None = None,
) -> SourceGovernanceReport:
    findings: list[SourceGovernanceFinding] = []
    strict_source_ids: set[str] = set()

    for score in source_quality_scores:
        source_id = str(score.get("source_id") or "")
        if not source_id:
            continue
        reliability_score = _float(score.get("reliability_score"), default=0.0)
        traceability_score = _float(score.get("traceability_score"), default=0.0)
        quality_score = _float(score.get("quality_score"), default=0.0)
        if reliability_score <= 0.4:
            strict_source_ids.add(source_id)
            findings.append(
                SourceGovernanceFinding(
                    finding_type="low_reliability_source",
                    severity="warning",
                    source_id=source_id,
                    message="Low-reliability source item requires stricter downstream verification.",
                    action="require_stricter_verification",
                    metadata={"reliability_score": reliability_score},
                )
            )
        if traceability_score < 1.0:
            findings.append(
                SourceGovernanceFinding(
                    finding_type="weak_traceability",
                    severity="blocking",
                    source_id=source_id,
                    message="Source item has incomplete traceability and must not enter final reports unchecked.",
                    action="exclude_or_repair_traceability",
                    metadata={"traceability_score": traceability_score},
                )
            )
        if quality_score < 0.65:
            findings.append(
                SourceGovernanceFinding(
                    finding_type="low_source_quality",
                    severity="warning",
                    source_id=source_id,
                    message="Source item quality score is below the governance threshold.",
                    action="review_source_quality",
                    metadata={"quality_score": quality_score},
                )
            )

    for source in _selected_sources(source_selection_report):
        source_id = str(source.get("source_id") or "")
        if not source_id:
            continue
        source_type = str(source.get("source_type") or "").casefold()
        category = _normalize_category(source.get("category"))
        if source_type in COMMUNITY_SOURCE_TYPES or category in COMMUNITY_CATEGORIES:
            strict_source_ids.add(source_id)
            findings.append(
                SourceGovernanceFinding(
                    finding_type="community_source_requires_verification",
                    severity="warning",
                    source_id=source_id,
                    message="Community source requires stricter verifier treatment.",
                    action="require_stricter_verification",
                    metadata={"source_type": source_type, "category": category},
                )
            )

    return SourceGovernanceReport(
        finding_count=len(findings),
        blocking_finding_count=sum(1 for finding in findings if finding.severity == "blocking"),
        requires_strict_verification_source_ids=sorted(strict_source_ids),
        findings=findings,
    )


def _selected_sources(source_selection_report: Any | None) -> list[dict[str, Any]]:
    if source_selection_report is None:
        return []
    if hasattr(source_selection_report, "selected_sources"):
        values = source_selection_report.selected_sources
    elif isinstance(source_selection_report, dict):
        values = source_selection_report.get("selected_sources", [])
    else:
        values = []
    return [dict(value) for value in values if isinstance(value, dict)]


def _normalize_category(value: Any) -> str | None:
    if value is None:
        return None
    return " ".join(str(value).casefold().replace("-", " ").replace("_", " ").split()).replace(" ", "_")


def _float(value: Any, *, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default
