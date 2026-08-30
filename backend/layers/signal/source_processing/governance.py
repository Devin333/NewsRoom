from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from backend.foundation.models.source import SourceGovernanceFinding, SourceGovernanceReport


COMMUNITY_SOURCE_TYPES = {
    "hackernews",
    "reddit",
    "lobsters",
    "stackoverflow",
    "devto",
    "medium",
}
COMMUNITY_CATEGORIES = {"community", "developer_community", "social"}
OFFICIAL_SOURCE_TYPES = {"official_blog", "github", "arxiv"}
OFFICIAL_CATEGORIES = {"official", "primary", "vendor", "research_lab"}


@dataclass(frozen=True)
class SourceGovernancePolicy:
    low_reliability_threshold: float = 0.4
    minimum_traceability_score: float = 1.0
    low_quality_threshold: float = 0.65
    community_source_types: set[str] = field(default_factory=lambda: set(COMMUNITY_SOURCE_TYPES))
    community_categories: set[str] = field(default_factory=lambda: set(COMMUNITY_CATEGORIES))
    official_source_types: set[str] = field(default_factory=lambda: set(OFFICIAL_SOURCE_TYPES))
    official_categories: set[str] = field(default_factory=lambda: set(OFFICIAL_CATEGORIES))
    require_strict_verification_for_community: bool = True
    require_traceability_for_final_report: bool = True
    official_priority_bonus_expected: bool = True

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "SourceGovernancePolicy":
        return cls(
            low_reliability_threshold=float(
                payload.get("low_reliability_threshold", cls.low_reliability_threshold)
            ),
            minimum_traceability_score=float(
                payload.get("minimum_traceability_score", cls.minimum_traceability_score)
            ),
            low_quality_threshold=float(payload.get("low_quality_threshold", cls.low_quality_threshold)),
            community_source_types=_string_set(
                payload.get("community_source_types"),
                default=COMMUNITY_SOURCE_TYPES,
            ),
            community_categories=_normalized_set(
                payload.get("community_categories"),
                default=COMMUNITY_CATEGORIES,
            ),
            official_source_types=_string_set(
                payload.get("official_source_types"),
                default=OFFICIAL_SOURCE_TYPES,
            ),
            official_categories=_normalized_set(
                payload.get("official_categories"),
                default=OFFICIAL_CATEGORIES,
            ),
            require_strict_verification_for_community=_bool_value(
                payload.get("require_strict_verification_for_community"),
                default=True,
            ),
            require_traceability_for_final_report=_bool_value(
                payload.get("require_traceability_for_final_report"),
                default=True,
            ),
            official_priority_bonus_expected=_bool_value(
                payload.get("official_priority_bonus_expected"),
                default=True,
            ),
        )


def build_source_governance_report(
    *,
    source_quality_scores: list[dict[str, Any]],
    source_selection_report: Any | None = None,
    policy: SourceGovernancePolicy | dict[str, Any] | None = None,
) -> SourceGovernanceReport:
    governance_policy = _policy(policy)
    findings: list[SourceGovernanceFinding] = []
    strict_source_ids: set[str] = set()
    selected_sources = _selected_sources(source_selection_report)
    social_source_ids = {
        source_id
        for source in selected_sources
        if (source_id := str(source.get("source_id") or ""))
        and _is_community_source(source, governance_policy)
    }

    for score in source_quality_scores:
        source_id = str(score.get("source_id") or "")
        if not source_id:
            continue
        if source_id not in social_source_ids and not _is_community_source(score, governance_policy):
            continue
        reliability_score = _float(score.get("reliability_score"), default=0.0)
        traceability_score = _float(score.get("traceability_score"), default=0.0)
        quality_score = _float(score.get("quality_score"), default=0.0)
        if reliability_score <= governance_policy.low_reliability_threshold:
            strict_source_ids.add(source_id)
            findings.append(
                SourceGovernanceFinding(
                    finding_type="low_reliability_source",
                    severity="warning",
                    source_id=source_id,
                    message="Low-reliability source item requires stricter downstream verification.",
                    action="require_stricter_verification",
                    metadata={
                        "reliability_score": reliability_score,
                        "threshold": governance_policy.low_reliability_threshold,
                    },
                )
            )
        if traceability_score < governance_policy.minimum_traceability_score:
            findings.append(
                SourceGovernanceFinding(
                    finding_type="weak_traceability",
                    severity=(
                        "blocking"
                        if governance_policy.require_traceability_for_final_report
                        else "warning"
                    ),
                    source_id=source_id,
                    message="Source item has incomplete traceability and must not enter final reports unchecked.",
                    action="exclude_or_repair_traceability",
                    metadata={
                        "traceability_score": traceability_score,
                        "threshold": governance_policy.minimum_traceability_score,
                    },
                )
            )
        if quality_score < governance_policy.low_quality_threshold:
            findings.append(
                SourceGovernanceFinding(
                    finding_type="low_source_quality",
                    severity="warning",
                    source_id=source_id,
                    message="Source item quality score is below the governance threshold.",
                    action="review_source_quality",
                    metadata={
                        "quality_score": quality_score,
                        "threshold": governance_policy.low_quality_threshold,
                    },
                )
            )

    for source in selected_sources:
        source_id = str(source.get("source_id") or "")
        if not source_id:
            continue
        source_type = str(source.get("source_type") or "").casefold()
        category = _normalize_category(source.get("category"))
        if _is_community_source(source, governance_policy) and governance_policy.require_strict_verification_for_community:
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


def _is_community_source(source: dict[str, Any], policy: SourceGovernancePolicy) -> bool:
    source_type = str(source.get("source_type") or "").casefold()
    category = _normalize_category(source.get("category"))
    return source_type in policy.community_source_types or category in policy.community_categories


def _normalize_category(value: Any) -> str | None:
    if value is None:
        return None
    return " ".join(str(value).casefold().replace("-", " ").replace("_", " ").split()).replace(" ", "_")


def _float(value: Any, *, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _policy(policy: SourceGovernancePolicy | dict[str, Any] | None) -> SourceGovernancePolicy:
    if policy is None:
        return SourceGovernancePolicy()
    if isinstance(policy, SourceGovernancePolicy):
        return policy
    return SourceGovernancePolicy.from_dict(dict(policy))


def _string_set(value: Any, *, default: set[str]) -> set[str]:
    if value is None:
        return set(default)
    if isinstance(value, str):
        return {item.strip().casefold() for item in value.split(",") if item.strip()}
    return {str(item).strip().casefold() for item in value if str(item).strip()}


def _normalized_set(value: Any, *, default: set[str]) -> set[str]:
    return {_normalize_category(item) or "" for item in _string_set(value, default=default)} - {""}


def _bool_value(value: Any, *, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().casefold() in {"1", "true", "yes", "on"}
