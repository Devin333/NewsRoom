from __future__ import annotations

from datetime import datetime, timezone as _tz
UTC = _tz.utc
from typing import Any

from pydantic import Field, field_validator, model_validator

from business.foundation.primitives import PrimitiveModel, SourceRef, build_stable_id, ensure_utc


class BusinessArtifactRef(PrimitiveModel):
    artifact_id: str
    artifact_type: str
    label: str | None = None
    uri: str | None = None
    run_id: str | None = None
    trace_ref: SourceRef | None = None
    manifest_ref: SourceRef | None = None
    source_ref: SourceRef | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("artifact_id", "artifact_type")
    @classmethod
    def _non_empty_text(cls, value: str) -> str:
        text = str(value).strip()
        if not text:
            raise ValueError("artifact ref text fields must be non-empty")
        return text

    @model_validator(mode="after")
    def _normalize_created_at(self) -> "BusinessArtifactRef":
        object.__setattr__(self, "created_at", ensure_utc(self.created_at) or self.created_at)
        return self

    @classmethod
    def create(
        cls,
        artifact_type: str,
        *,
        label: str | None = None,
        uri: str | None = None,
        run_id: str | None = None,
        trace_ref: SourceRef | None = None,
        manifest_ref: SourceRef | None = None,
        source_ref: SourceRef | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> "BusinessArtifactRef":
        return cls(
            artifact_id=build_stable_id("artifact", artifact_type, label or "", uri or "", run_id or ""),
            artifact_type=artifact_type,
            label=label,
            uri=uri,
            run_id=run_id,
            trace_ref=trace_ref,
            manifest_ref=manifest_ref,
            source_ref=source_ref,
            metadata=metadata or {},
        )


__all__ = ["BusinessArtifactRef"]
