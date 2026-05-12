from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from domain.sources import Lineage


@dataclass(frozen=True)
class EvidenceItem:
    evidence_id: str
    source_url: str
    title: str
    summary: str
    confidence: float
    source_id: str
    lineage: Lineage | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "evidence_id": self.evidence_id,
            "source_url": self.source_url,
            "title": self.title,
            "summary": self.summary,
            "confidence": self.confidence,
            "source_id": self.source_id,
            "lineage": self.lineage.to_dict() if self.lineage else None,
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class EvidenceBundle:
    bundle_id: str
    items: list[EvidenceItem]
    source_map: dict[str, list[str]] = field(default_factory=dict)
    missing_information: list[str] = field(default_factory=list)
    coverage_notes: list[str] = field(default_factory=list)
    lineage: Lineage | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def source_urls(self) -> set[str]:
        return {item.source_url for item in self.items}

    def to_dict(self) -> dict[str, Any]:
        return {
            "bundle_id": self.bundle_id,
            "items": [item.to_dict() for item in self.items],
            "source_map": {key: list(value) for key, value in self.source_map.items()},
            "missing_information": list(self.missing_information),
            "coverage_notes": list(self.coverage_notes),
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
