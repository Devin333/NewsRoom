from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from domain.sources import Lineage


def _utc_now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True)
class EvidenceItem:
    evidence_id: str
    source_url: str
    title: str
    summary: str
    confidence: float
    source_id: str
    source_item_id: str | None = None
    source_item_ids: list[str] = field(default_factory=list)
    source_urls: list[str] = field(default_factory=list)
    source_reliability: str | None = None
    publishable: bool = True
    evidence_type: str = "other"
    lineage: Lineage | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        source_item_ids = list(self.source_item_ids)
        if self.source_item_id and self.source_item_id not in source_item_ids:
            source_item_ids.insert(0, self.source_item_id)
        if not source_item_ids and self.lineage and self.lineage.source_item_id:
            source_item_ids.append(self.lineage.source_item_id)
        object.__setattr__(self, "source_item_ids", source_item_ids)
        object.__setattr__(
            self,
            "source_item_id",
            self.source_item_id or (source_item_ids[0] if source_item_ids else None),
        )
        source_urls = list(self.source_urls)
        if self.source_url and self.source_url not in source_urls:
            source_urls.insert(0, self.source_url)
        object.__setattr__(self, "source_urls", source_urls)
        publishable = self.publishable and bool(self.source_url)
        evidence_kind = str(self.metadata.get("evidence_kind") or self.metadata.get("source_type") or "")
        if not self.source_url and evidence_kind not in {"internal", "manual"}:
            publishable = False
        object.__setattr__(self, "publishable", publishable)

    def to_dict(self) -> dict[str, Any]:
        return {
            "evidence_id": self.evidence_id,
            "source_url": self.source_url,
            "source_urls": list(self.source_urls),
            "title": self.title,
            "summary": self.summary,
            "confidence": self.confidence,
            "source_id": self.source_id,
            "source_item_id": self.source_item_id,
            "source_item_ids": list(self.source_item_ids),
            "source_reliability": self.source_reliability,
            "publishable": self.publishable,
            "evidence_type": self.evidence_type,
            "lineage": self.lineage.to_dict() if self.lineage else None,
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class EvidenceBundle:
    bundle_id: str
    items: list[EvidenceItem]
    topic: str = ""
    created_at: datetime = field(default_factory=_utc_now)
    source_map: dict[str, list[str]] = field(default_factory=dict)
    missing_information: list[str] = field(default_factory=list)
    coverage_notes: list[str] = field(default_factory=list)
    source_coverage: dict[str, Any] = field(default_factory=dict)
    lineage: Lineage | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.source_map:
            source_map: dict[str, list[str]] = {}
            for item in self.items:
                for url in item.source_urls or ([item.source_url] if item.source_url else []):
                    source_map.setdefault(url, []).append(item.evidence_id)
            object.__setattr__(self, "source_map", source_map)
        if not self.source_coverage:
            source_ids = {
                source_id
                for item in self.items
                for source_id in ([item.source_id] if item.source_id else [])
            }
            object.__setattr__(
                self,
                "source_coverage",
                {
                    "item_count": len(self.items),
                    "source_count": len(source_ids),
                    "source_url_count": len(self.source_urls),
                    "publishable_item_count": sum(1 for item in self.items if item.publishable),
                },
            )

    @property
    def source_urls(self) -> set[str]:
        urls: set[str] = set()
        for item in self.items:
            urls.update(url for url in item.source_urls if url)
            if item.source_url:
                urls.add(item.source_url)
        return urls

    @property
    def evidence_ids(self) -> set[str]:
        return {item.evidence_id for item in self.items}

    @property
    def item_count(self) -> int:
        return len(self.items)

    def to_dict(self) -> dict[str, Any]:
        return {
            "bundle_id": self.bundle_id,
            "topic": self.topic,
            "created_at": self.created_at.isoformat().replace("+00:00", "Z"),
            "item_count": self.item_count,
            "items": [item.to_dict() for item in self.items],
            "source_map": {key: list(value) for key, value in self.source_map.items()},
            "missing_information": list(self.missing_information),
            "coverage_notes": list(self.coverage_notes),
            "source_coverage": dict(self.source_coverage),
            "lineage": self.lineage.to_dict() if self.lineage else None,
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class EvidenceScore:
    evidence_id: str
    source_reliability_score: float
    freshness_score: float
    specificity_score: float
    corroboration_score: float
    extraction_confidence_score: float
    final_confidence: float
    score_reason: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "evidence_id": self.evidence_id,
            "source_reliability_score": self.source_reliability_score,
            "freshness_score": self.freshness_score,
            "specificity_score": self.specificity_score,
            "corroboration_score": self.corroboration_score,
            "extraction_confidence_score": self.extraction_confidence_score,
            "final_confidence": self.final_confidence,
            "score_reason": self.score_reason,
        }


@dataclass(frozen=True)
class Claim:
    claim_id: str
    text: str
    claim_type: str
    section_id: str = "global"
    severity: str = "medium"
    importance: str = "medium"
    source_evidence_ids: list[str] = field(default_factory=list)
    source_urls: list[str] = field(default_factory=list)
    confidence: float | None = None
    created_by_agent_id: str | None = None
    lineage: Lineage | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "claim_id": self.claim_id,
            "text": self.text,
            "claim_type": self.claim_type,
            "section_id": self.section_id,
            "severity": self.severity,
            "importance": self.importance,
            "source_evidence_ids": list(self.source_evidence_ids),
            "source_urls": list(self.source_urls),
            "confidence": self.confidence,
            "created_by_agent_id": self.created_by_agent_id,
            "lineage": self.lineage.to_dict() if self.lineage else None,
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class VerifiedClaim:
    claim_id: str
    claim: str
    status: str
    confidence: float
    supporting_evidence_ids: list[str] = field(default_factory=list)
    supporting_sources: list[str] = field(default_factory=list)
    rejecting_evidence_ids: list[str] = field(default_factory=list)
    rejecting_sources: list[str] = field(default_factory=list)
    notes: str | None = None
    rejection_reason: str | None = None
    uncertainty_reason: str | None = None
    section_id: str = "global"
    severity: str = "medium"
    importance: str = "medium"
    verification_method: str = "rule"
    lineage: Lineage | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "claim_id": self.claim_id,
            "claim": self.claim,
            "status": self.status,
            "confidence": self.confidence,
            "supporting_evidence_ids": list(self.supporting_evidence_ids),
            "supporting_sources": list(self.supporting_sources),
            "rejecting_evidence_ids": list(self.rejecting_evidence_ids),
            "rejecting_sources": list(self.rejecting_sources),
            "notes": self.notes,
            "rejection_reason": self.rejection_reason,
            "uncertainty_reason": self.uncertainty_reason,
            "section_id": self.section_id,
            "severity": self.severity,
            "importance": self.importance,
            "verification_method": self.verification_method,
            "lineage": self.lineage.to_dict() if self.lineage else None,
        }


@dataclass(frozen=True)
class VerifiedFindings:
    accepted_claims: list[VerifiedClaim] = field(default_factory=list)
    rejected_claims: list[VerifiedClaim] = field(default_factory=list)
    uncertain_claims: list[VerifiedClaim] = field(default_factory=list)
    source_quality_notes: list[str] = field(default_factory=list)
    verification_summary: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def all_claims(self) -> list[VerifiedClaim]:
        return [*self.accepted_claims, *self.rejected_claims, *self.uncertain_claims]

    def to_dict(self) -> dict[str, Any]:
        return {
            "accepted_claims": [claim.to_dict() for claim in self.accepted_claims],
            "rejected_claims": [claim.to_dict() for claim in self.rejected_claims],
            "uncertain_claims": [claim.to_dict() for claim in self.uncertain_claims],
            "source_quality_notes": list(self.source_quality_notes),
            "verification_summary": self.verification_summary,
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class EvidenceBuildResult:
    bundle: EvidenceBundle
    evidence_scores: list[EvidenceScore]
    candidate_claims: list[Claim] = field(default_factory=list)
    verified_findings: VerifiedFindings | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "bundle": self.bundle.to_dict(),
            "evidence_scores": [score.to_dict() for score in self.evidence_scores],
            "candidate_claims": [claim.to_dict() for claim in self.candidate_claims],
            "verified_findings": (
                self.verified_findings.to_dict() if self.verified_findings else None
            ),
        }
