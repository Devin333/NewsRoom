from __future__ import annotations

from datetime import datetime, timezone as _tz
UTC = _tz.utc
from typing import Any

from pydantic import Field, field_validator, model_validator

from backend.foundation.primitives import PrimitiveModel, SourceRef, build_stable_id, ensure_utc


class BusinessEvidenceRef(PrimitiveModel):
    evidence_id: str
    evidence_type: str
    source_ref: SourceRef
    relation_ids: list[str] = Field(default_factory=list)
    claim_ids: list[str] = Field(default_factory=list)
    signal_ids: list[str] = Field(default_factory=list)
    confidence: float | None = None
    collected_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("evidence_id", "evidence_type")
    @classmethod
    def _non_empty_text(cls, value: str) -> str:
        text = str(value).strip()
        if not text:
            raise ValueError("evidence ref text fields must be non-empty")
        return text

    @field_validator("confidence")
    @classmethod
    def _optional_unit_interval(cls, value: float | None) -> float | None:
        if value is None:
            return None
        numeric = float(value)
        if not 0.0 <= numeric <= 1.0:
            raise ValueError("evidence confidence must be between 0 and 1")
        return round(numeric, 4)

    @model_validator(mode="after")
    def _normalize_collected_at(self) -> "BusinessEvidenceRef":
        object.__setattr__(self, "collected_at", ensure_utc(self.collected_at) or self.collected_at)
        return self

    @classmethod
    def from_source(
        cls,
        source_ref: SourceRef,
        *,
        evidence_type: str = "source_evidence",
        relation_ids: list[str] | None = None,
        claim_ids: list[str] | None = None,
        signal_ids: list[str] | None = None,
        confidence: float | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> "BusinessEvidenceRef":
        return cls(
            evidence_id=build_stable_id(
                "evidence",
                evidence_type,
                source_ref.source_id or "",
                relation_ids or [],
                claim_ids or [],
                signal_ids or [],
            ),
            evidence_type=evidence_type,
            source_ref=source_ref,
            relation_ids=relation_ids or [],
            claim_ids=claim_ids or [],
            signal_ids=signal_ids or [],
            confidence=confidence,
            metadata=metadata or {},
        )


class BusinessTraceRef(PrimitiveModel):
    trace_id: str
    run_id: str | None = None
    graph_id: str | None = None
    graph_version: str | None = None
    graph_ref: str | None = None
    source_ref: SourceRef | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("trace_id")
    @classmethod
    def _non_empty_trace_id(cls, value: str) -> str:
        text = str(value).strip()
        if not text:
            raise ValueError("trace_id is required")
        return text

    @model_validator(mode="after")
    def _validate_graph_identity(self) -> "BusinessTraceRef":
        values = (self.graph_id, self.graph_version, self.graph_ref)
        if any(value is not None for value in values):
            if not self.graph_id or not self.graph_version or not self.graph_ref:
                raise ValueError("graph_id, graph_version, and graph_ref must be provided together")
            if self.graph_ref != f"{self.graph_id}@{self.graph_version}":
                raise ValueError("graph_ref must match graph_id and graph_version")
        return self

    @classmethod
    def create(
        cls,
        *,
        run_id: str,
        graph_id: str | None = None,
        graph_version: str | None = None,
        graph_ref: str | None = None,
        source_ref: SourceRef | None = None,
    ) -> "BusinessTraceRef":
        resolved_graph_ref = graph_ref
        if resolved_graph_ref is None and graph_id and graph_version:
            resolved_graph_ref = f"{graph_id}@{graph_version}"
        return cls(
            trace_id=build_stable_id("trace", run_id, resolved_graph_ref or ""),
            run_id=run_id,
            graph_id=graph_id,
            graph_version=graph_version,
            graph_ref=resolved_graph_ref,
            source_ref=source_ref,
        )


class BusinessRunManifestRef(PrimitiveModel):
    manifest_id: str
    run_id: str
    uri: str | None = None
    source_ref: SourceRef | None = None
    artifact_ids: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("manifest_id", "run_id")
    @classmethod
    def _non_empty_text(cls, value: str) -> str:
        text = str(value).strip()
        if not text:
            raise ValueError("manifest ref text fields must be non-empty")
        return text

    @classmethod
    def create(
        cls,
        *,
        run_id: str,
        uri: str | None = None,
        source_ref: SourceRef | None = None,
        artifact_ids: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> "BusinessRunManifestRef":
        return cls(
            manifest_id=build_stable_id("manifest", run_id, uri or "", artifact_ids or []),
            run_id=run_id,
            uri=uri,
            source_ref=source_ref,
            artifact_ids=artifact_ids or [],
            metadata=metadata or {},
        )


__all__ = ["BusinessEvidenceRef", "BusinessTraceRef", "BusinessRunManifestRef"]
