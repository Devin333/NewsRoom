from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import Field, field_validator, model_validator

from backend.foundation import PrimitiveModel, canonicalize_url, normalize_key
from backend.research.domain.common import (
    GateResult,
    SourceLineage,
    bounded_float,
    ensure_utc,
    require_text,
    unique_texts,
)


ResearchSourceType = Literal[
    "arxiv",
    "openreview",
    "doi",
    "crossref",
    "publisher",
    "local",
    "github",
    "manual",
    "other",
]

SourceAccessStatus = Literal["available", "metadata_only", "denied", "failed"]
CatalogRelationStatus = Literal["candidate", "verified", "rejected", "conflicting"]
CatalogRelationType = Literal[
    "paper_task",
    "paper_method",
    "paper_dataset",
    "paper_benchmark",
    "paper_metric",
    "paper_score",
    "paper_code_repository",
]
CatalogTargetType = Literal[
    "task",
    "method",
    "dataset",
    "benchmark",
    "metric",
    "score",
    "code_repository",
]


class ResearchSourceSnapshot(PrimitiveModel):
    """Immutable observation of one source used to build a research record."""

    snapshot_id: str
    paper_id: str
    source_type: ResearchSourceType = "other"
    canonical_url: str | None = None
    external_id: str | None = None
    content_type: str | None = None
    source_hash: str | None = None
    fetched_at: datetime | None = None
    access_status: SourceAccessStatus = "available"
    lineage: SourceLineage
    artifact_refs: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("snapshot_id", "paper_id")
    @classmethod
    def _required_ids(cls, value: str) -> str:
        return require_text(value, "source snapshot identity fields")

    @field_validator("canonical_url")
    @classmethod
    def _normalize_url(cls, value: str | None) -> str | None:
        text = value.strip() if value is not None else None
        return canonicalize_url(text) if text else None

    @field_validator("external_id", "content_type", "source_hash")
    @classmethod
    def _normalize_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        text = value.strip()
        return text or None

    @model_validator(mode="after")
    def _validate_locator(self) -> "ResearchSourceSnapshot":
        if not self.canonical_url and not self.external_id and not self.artifact_refs:
            raise ValueError("source snapshot requires canonical_url, external_id, or artifact_refs")
        self.lineage.require_refs("source snapshot requires source lineage")
        object.__setattr__(self, "artifact_refs", unique_texts(self.artifact_refs))
        if self.fetched_at is not None:
            object.__setattr__(self, "fetched_at", ensure_utc(self.fetched_at))
        return self


class ResearchPaperIdentity(PrimitiveModel):
    """Canonical identity and stable external identifiers for a paper."""

    paper_id: str
    title: str
    authors: list[str] = Field(default_factory=list)
    published_year: int | None = None
    canonical_url: str | None = None
    arxiv_id: str | None = None
    doi: str | None = None
    openreview_id: str | None = None
    versions: list[str] = Field(default_factory=list)
    source_snapshot_ids: list[str] = Field(default_factory=list)
    fingerprint: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("paper_id", "title")
    @classmethod
    def _required_text(cls, value: str) -> str:
        return require_text(value, "paper identity fields")

    @field_validator("authors", "versions", "source_snapshot_ids")
    @classmethod
    def _unique_values(cls, value: list[str]) -> list[str]:
        return unique_texts(value)

    @field_validator("canonical_url")
    @classmethod
    def _normalize_url(cls, value: str | None) -> str | None:
        text = value.strip() if value is not None else None
        return canonicalize_url(text) if text else None

    @model_validator(mode="after")
    def _derive_fingerprint(self) -> "ResearchPaperIdentity":
        fingerprint = self.fingerprint or build_paper_identity_fingerprint(
            self.title,
            self.authors,
            self.published_year,
        )
        object.__setattr__(self, "fingerprint", fingerprint)
        return self


class ResearchPaperRelation(PrimitiveModel):
    relation_id: str
    paper_id: str
    relation_type: CatalogRelationType
    target_type: CatalogTargetType
    target_id: str
    status: CatalogRelationStatus = "candidate"
    confidence: float = 0.0
    source_snapshot_refs: list[str]
    evidence_refs: list[str]
    created_at: datetime | None = None
    observed_at: datetime | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("relation_id", "paper_id", "target_id")
    @classmethod
    def _required_text(cls, value: str) -> str:
        return require_text(value, "paper relation fields")

    @field_validator("confidence")
    @classmethod
    def _bounded_confidence(cls, value: float) -> float:
        return bounded_float(value, "relation confidence")

    @field_validator("source_snapshot_refs", "evidence_refs")
    @classmethod
    def _required_refs(cls, value: list[str]) -> list[str]:
        refs = unique_texts(value)
        if not refs:
            raise ValueError("paper relation requires source and evidence refs")
        return refs

    @model_validator(mode="after")
    def _validate_relation(self) -> "ResearchPaperRelation":
        expected = {
            "paper_task": "task",
            "paper_method": "method",
            "paper_dataset": "dataset",
            "paper_benchmark": "benchmark",
            "paper_metric": "metric",
            "paper_score": "score",
            "paper_code_repository": "code_repository",
        }[self.relation_type]
        if self.target_type != expected:
            raise ValueError(f"{self.relation_type} requires target_type={expected}")
        if self.status == "verified" and (not self.source_snapshot_refs or not self.evidence_refs):
            raise ValueError("verified paper relation requires source and evidence refs")
        for field_name in ("created_at", "observed_at"):
            value = getattr(self, field_name)
            if value is not None:
                object.__setattr__(self, field_name, ensure_utc(value))
        return self


class ResearchPaperCatalogEntry(PrimitiveModel):
    entry_id: str
    paper_id: str
    identity: ResearchPaperIdentity
    relations: list[ResearchPaperRelation] = Field(default_factory=list)
    status: Literal["catalog_partial", "catalog_ready"] = "catalog_partial"
    source_snapshot_refs: list[str] = Field(default_factory=list)
    created_at: datetime | None = None
    updated_at: datetime | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("entry_id", "paper_id")
    @classmethod
    def _required_ids(cls, value: str) -> str:
        return require_text(value, "catalog entry identity fields")

    @field_validator("source_snapshot_refs")
    @classmethod
    def _unique_source_refs(cls, value: list[str]) -> list[str]:
        return unique_texts(value)

    @model_validator(mode="after")
    def _validate_entry(self) -> "ResearchPaperCatalogEntry":
        if self.identity.paper_id != self.paper_id:
            raise ValueError("catalog identity must match paper_id")
        seen: set[str] = set()
        deduped: list[ResearchPaperRelation] = []
        for relation in self.relations:
            if relation.paper_id != self.paper_id:
                raise ValueError("catalog relations must match paper_id")
            if relation.relation_id not in seen:
                seen.add(relation.relation_id)
                deduped.append(relation)
        object.__setattr__(self, "relations", deduped)
        for field_name in ("created_at", "updated_at"):
            value = getattr(self, field_name)
            if value is not None:
                object.__setattr__(self, field_name, ensure_utc(value))
        return self


def build_paper_identity_fingerprint(
    title: str,
    authors: list[str] | tuple[str, ...] = (),
    published_year: int | None = None,
) -> str:
    """Build a deterministic fallback key for identity matching."""

    normalized_title = normalize_key(require_text(title, "paper title"))
    normalized_authors = ",".join(sorted(normalize_key(author) for author in authors if str(author).strip()))
    year = str(published_year or "")
    return "|".join(part for part in (normalized_title, normalized_authors, year) if part)


def same_paper_identity(left: ResearchPaperIdentity, right: ResearchPaperIdentity) -> bool:
    """Compare identities using external IDs, canonical URL, then fingerprint."""

    for left_value, right_value in (
        (left.arxiv_id, right.arxiv_id),
        (left.doi, right.doi),
        (left.openreview_id, right.openreview_id),
        (left.canonical_url, right.canonical_url),
        (left.fingerprint, right.fingerprint),
    ):
        if left_value and right_value and normalize_key(left_value) == normalize_key(right_value):
            return True
    return False


def validate_relation_for_publication(relation: ResearchPaperRelation) -> GateResult:
    """A relation can be published as verified only with complete lineage."""

    if relation.status != "verified":
        return GateResult.fail(
            "CatalogRelationVerificationGate",
            "catalog relation is not verified",
            metadata={"status": relation.status},
        )
    if not relation.source_snapshot_refs or not relation.evidence_refs:
        return GateResult.fail(
            "CatalogRelationEvidenceGate",
            "verified catalog relation requires source and evidence refs",
        )
    return GateResult.pass_("CatalogRelationVerificationGate")


def metric_compatibility_key(
    *,
    dataset_id: str,
    dataset_version: str | None,
    metric_id: str,
    metric_direction: str,
    metric_unit: str | None,
    split: str | None,
    evaluation_protocol: str | None,
) -> tuple[str, str, str, str, str, str, str]:
    """Return the normalized fields required for deterministic score comparison."""

    def _dimension(value: str | None) -> str:
        return str(value or "").strip().casefold()

    return (
        normalize_key(dataset_id),
        _dimension(dataset_version),
        normalize_key(metric_id),
        _dimension(metric_direction),
        _dimension(metric_unit),
        _dimension(split),
        _dimension(evaluation_protocol),
    )


__all__ = [
    "CatalogRelationStatus",
    "CatalogRelationType",
    "CatalogTargetType",
    "ResearchPaperCatalogEntry",
    "ResearchPaperIdentity",
    "ResearchPaperRelation",
    "ResearchSourceSnapshot",
    "ResearchSourceType",
    "SourceAccessStatus",
    "build_paper_identity_fingerprint",
    "metric_compatibility_key",
    "same_paper_identity",
    "validate_relation_for_publication",
]
