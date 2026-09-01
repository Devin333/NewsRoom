from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from hashlib import sha256
from typing import Any, Literal

from pydantic import Field, field_validator, model_validator

from backend.foundation import PrimitiveModel, normalize_key
from backend.research.domain.common import require_text, unique_texts


class ResearchBenchmark(PrimitiveModel):
    benchmark_id: str
    name: str
    task: str
    dataset_ids: list[str] = Field(default_factory=list)
    actor_scope: dict[str, str] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("benchmark_id", "name", "task")
    @classmethod
    def _required_text(cls, value: str) -> str:
        return require_text(value, "benchmark fields")

    @model_validator(mode="after")
    def _normalize_dataset_ids(self) -> "ResearchBenchmark":
        object.__setattr__(self, "benchmark_id", normalize_key(self.benchmark_id))
        object.__setattr__(self, "dataset_ids", unique_texts(self.dataset_ids))
        scope = _normalized_scope(self.metadata)
        scope.update(_normalized_scope(self.actor_scope))
        object.__setattr__(self, "actor_scope", scope)
        if scope:
            object.__setattr__(self, "metadata", {**dict(self.metadata), "actor_scope": scope})
        return self


class ResearchDataset(PrimitiveModel):
    dataset_id: str
    name: str
    version: str | None = None
    source_refs: list[str] = Field(default_factory=list)
    actor_scope: dict[str, str] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("dataset_id", "name")
    @classmethod
    def _required_text(cls, value: str) -> str:
        return require_text(value, "dataset fields")

    @model_validator(mode="after")
    def _normalize_scope(self) -> "ResearchDataset":
        scope = _normalized_scope(self.metadata)
        scope.update(_normalized_scope(self.actor_scope))
        object.__setattr__(self, "actor_scope", scope)
        if scope:
            object.__setattr__(self, "metadata", {**dict(self.metadata), "actor_scope": scope})
        return self


class ResearchMetric(PrimitiveModel):
    metric_id: str
    name: str
    direction: Literal["higher_is_better", "lower_is_better"] = "higher_is_better"
    unit: str | None = None
    actor_scope: dict[str, str] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("metric_id", "name")
    @classmethod
    def _required_text(cls, value: str) -> str:
        return require_text(value, "metric fields")

    @model_validator(mode="after")
    def _normalize_scope(self) -> "ResearchMetric":
        scope = _normalized_scope(self.metadata)
        scope.update(_normalized_scope(self.actor_scope))
        object.__setattr__(self, "actor_scope", scope)
        if scope:
            object.__setattr__(self, "metadata", {**dict(self.metadata), "actor_scope": scope})
        return self


class ResearchScore(PrimitiveModel):
    score_id: str
    paper_id: str
    benchmark_id: str
    dataset_id: str
    metric_id: str
    value: float
    baseline_id: str | None = None
    baseline_ref: str | None = None
    source_refs: list[str] = Field(default_factory=list)
    source_snapshot_refs: list[str] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)
    verification_status: Literal["candidate", "verified", "rejected", "conflicting"] = "candidate"
    status: Literal["candidate", "verified", "rejected", "conflicting"] | None = None
    split: str | None = None
    unit: str | None = None
    direction: Literal["higher_is_better", "lower_is_better"] | None = None
    dataset_version: str | None = None
    evaluation_protocol: str | None = None
    # ``value`` is retained as the backwards-compatible comparison value.
    # The fields below keep the original observation separate from the value
    # selected by a deterministic normalization contract.
    raw_display_value: str | None = None
    normalized_value: float | None = None
    unit_conversion: str | None = None
    rounding_mode: str | None = None
    normalization_version: str | None = None
    uncertainty: float | None = None
    sample_count: int | None = None
    seed_count: int | None = None
    protocol_fingerprint: str | None = None
    selection_policy: str | None = None
    checkpoint_ref: str | None = None
    observed_at: datetime | None = None
    actor_scope: dict[str, str] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("score_id", "paper_id", "benchmark_id", "dataset_id", "metric_id")
    @classmethod
    def _required_text(cls, value: str) -> str:
        return require_text(value, "score fields")

    @model_validator(mode="after")
    def _require_refs_and_range(self) -> "ResearchScore":
        refs = unique_texts(self.source_refs)
        snapshot_refs = unique_texts(self.source_snapshot_refs)
        metadata_snapshot_refs = self.metadata.get("source_snapshot_refs")
        if not snapshot_refs and isinstance(metadata_snapshot_refs, (list, tuple)):
            snapshot_refs = unique_texts([str(item) for item in metadata_snapshot_refs])
        # ``source_refs`` predates the v1 typed contract. Keep it as the
        # compatibility locator while exposing the canonical snapshot field.
        if not refs and snapshot_refs:
            refs = list(snapshot_refs)
        if not snapshot_refs and refs:
            snapshot_refs = list(refs)
        if not refs:
            raise ValueError("benchmark score requires source refs")
        if not -1_000_000_000 <= float(self.value) <= 1_000_000_000:
            raise ValueError("benchmark score is outside supported range")
        if self.normalized_value is not None and not -1_000_000_000 <= float(self.normalized_value) <= 1_000_000_000:
            raise ValueError("normalized benchmark score is outside supported range")
        if self.uncertainty is not None and float(self.uncertainty) < 0:
            raise ValueError("benchmark score uncertainty must be non-negative")
        for field_name in ("sample_count", "seed_count"):
            value = getattr(self, field_name)
            if value is not None and (isinstance(value, bool) or int(value) < 0):
                raise ValueError(f"benchmark score {field_name} must be non-negative")
        object.__setattr__(self, "source_refs", refs)
        object.__setattr__(self, "source_snapshot_refs", snapshot_refs)
        object.__setattr__(self, "evidence_refs", unique_texts(self.evidence_refs))
        baseline = self.baseline_ref or self.baseline_id
        object.__setattr__(self, "baseline_ref", baseline)
        object.__setattr__(self, "baseline_id", self.baseline_id or baseline)
        normalized_value = float(self.value) if self.normalized_value is None else float(self.normalized_value)
        object.__setattr__(self, "normalized_value", normalized_value)
        object.__setattr__(self, "value", normalized_value)
        raw_display = self.raw_display_value
        if raw_display is None:
            raw_display = str(self.value)
        raw_display = str(raw_display).strip()
        object.__setattr__(self, "raw_display_value", raw_display or None)
        status = self.status or self.verification_status
        object.__setattr__(self, "verification_status", status)
        object.__setattr__(self, "status", status)
        if self.dataset_version is None:
            metadata_version = self.metadata.get("dataset_version")
            if metadata_version is not None and str(metadata_version).strip():
                object.__setattr__(self, "dataset_version", str(metadata_version).strip())
        elif self.dataset_version.strip():
            object.__setattr__(
                self,
                "metadata",
                {**dict(self.metadata), "dataset_version": self.dataset_version.strip()},
            )
        else:
            object.__setattr__(self, "dataset_version", None)
        protocol_fingerprint = self.protocol_fingerprint or _score_protocol_fingerprint(self)
        object.__setattr__(self, "protocol_fingerprint", protocol_fingerprint)
        metadata = dict(self.metadata)
        protocol_fields = _score_protocol_fields(self)
        metadata.update(
            {
                "raw_display_value": self.raw_display_value,
                "normalized_value": normalized_value,
                "normalization_version": self.normalization_version or "research-score-normalization-v1",
                "protocol_fingerprint": protocol_fingerprint,
                "protocol_unknown_fields": [
                    name for name, value in protocol_fields.items() if value == "unknown"
                ],
            }
        )
        object.__setattr__(self, "metadata", metadata)
        scope = _normalized_scope(self.metadata)
        scope.update(_normalized_scope(self.actor_scope))
        object.__setattr__(self, "actor_scope", scope)
        if scope:
            object.__setattr__(self, "metadata", {**dict(self.metadata), "actor_scope": scope})
        if self.observed_at is None:
            object.__setattr__(self, "observed_at", datetime.now(UTC))
        else:
            object.__setattr__(self, "observed_at", _ensure_utc(self.observed_at))
        if self.verification_status == "verified" and not self.evidence_refs:
            raise ValueError("verified benchmark score requires evidence refs")
        return self


class ResearchBaseline(PrimitiveModel):
    baseline_id: str
    name: str
    paper_id: str | None = None
    benchmark_id: str
    dataset_id: str
    metric_id: str
    value: float | None = None
    source_refs: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("baseline_id", "name", "benchmark_id", "dataset_id", "metric_id")
    @classmethod
    def _required_text(cls, value: str) -> str:
        return require_text(value, "baseline fields")


class ResearchSOTAClaim(PrimitiveModel):
    claim_id: str
    paper_id: str
    # Candidate extraction may discover an assertion before it can resolve
    # the benchmark taxonomy. Keep the claim queryable with explicit missing
    # fields; verified claims still require all three typed references.
    benchmark_id: str = ""
    dataset_id: str = ""
    metric_id: str = ""
    score_id: str | None = None
    claim_text: str
    verification_status: Literal["candidate", "verified", "rejected", "conflicting"] = "candidate"
    status: Literal["candidate", "verified", "rejected", "conflicting"] | None = None
    source_refs: list[str] = Field(default_factory=list)
    source_snapshot_refs: list[str] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)
    dataset_version: str | None = None
    split: str | None = None
    unit: str | None = None
    direction: Literal["higher_is_better", "lower_is_better"] | None = None
    evaluation_protocol: str | None = None
    observed_at: datetime | None = None
    actor_scope: dict[str, str] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("claim_id", "paper_id", "claim_text")
    @classmethod
    def _required_text(cls, value: str) -> str:
        return require_text(value, "SOTA claim fields")

    @field_validator("benchmark_id", "dataset_id", "metric_id")
    @classmethod
    def _normalize_reference_id(cls, value: str | None) -> str:
        return str(value or "").strip()

    @model_validator(mode="after")
    def _normalize(self) -> "ResearchSOTAClaim":
        refs = unique_texts(self.source_refs)
        snapshot_refs = unique_texts(self.source_snapshot_refs)
        metadata_snapshot_refs = self.metadata.get("source_snapshot_refs")
        if not snapshot_refs and isinstance(metadata_snapshot_refs, (list, tuple)):
            snapshot_refs = unique_texts([str(item) for item in metadata_snapshot_refs])
        if not refs and snapshot_refs:
            refs = list(snapshot_refs)
        if not snapshot_refs and refs:
            snapshot_refs = list(refs)
        if not refs:
            raise ValueError("SOTA claim requires source refs")
        object.__setattr__(self, "source_refs", refs)
        object.__setattr__(self, "source_snapshot_refs", snapshot_refs)
        object.__setattr__(self, "evidence_refs", unique_texts(self.evidence_refs))
        status = self.status or self.verification_status
        object.__setattr__(self, "verification_status", status)
        object.__setattr__(self, "status", status)
        unresolved = [
            name
            for name, value in (
                ("benchmark_id", self.benchmark_id),
                ("dataset_id", self.dataset_id),
                ("metric_id", self.metric_id),
            )
            if not str(value or "").strip()
        ]
        if unresolved and status != "verified":
            object.__setattr__(
                self,
                "metadata",
                {**dict(self.metadata), "unresolved_fields": unresolved},
            )
        scope = _normalized_scope(self.metadata)
        scope.update(_normalized_scope(self.actor_scope))
        object.__setattr__(self, "actor_scope", scope)
        if scope:
            object.__setattr__(self, "metadata", {**dict(self.metadata), "actor_scope": scope})
        if self.observed_at is None:
            object.__setattr__(self, "observed_at", datetime.now(UTC))
        else:
            object.__setattr__(self, "observed_at", _ensure_utc(self.observed_at))
        if self.verification_status == "verified":
            missing = [
                name
                for name, value in (
                    ("score_id", self.score_id),
                    ("benchmark_id", self.benchmark_id),
                    ("dataset_id", self.dataset_id),
                    ("metric_id", self.metric_id),
                    ("source_snapshot_refs", self.source_snapshot_refs),
                    ("evidence_refs", self.evidence_refs),
                    ("dataset_version", self.dataset_version),
                    ("split", self.split),
                    ("unit", self.unit),
                    ("direction", self.direction),
                    ("evaluation_protocol", self.evaluation_protocol),
                )
                if value is None or (isinstance(value, (list, tuple, set)) and not value) or not str(value).strip()
            ]
            if missing:
                raise ValueError(
                    "verified SOTA claim requires " + ", ".join(missing)
                )
        return self


def _normalized_scope(value: Mapping[str, Any] | None) -> dict[str, str]:
    if not isinstance(value, Mapping):
        return {}
    source: dict[str, Any] = dict(value)
    nested = source.get("actor_scope")
    if isinstance(nested, Mapping):
        source.update(dict(nested))
    allowed = {"tenant_id", "user_id", "memory_namespace"}
    return {
        str(key): str(raw).strip()
        for key, raw in source.items()
        if str(key) in allowed and str(raw).strip()
    }


def _score_protocol_fields(score: ResearchScore) -> dict[str, str]:
    """Return the canonical comparison dimensions for a score observation.

    The fingerprint is deliberately derived from explicit typed fields first,
    then from metadata.  Missing dimensions remain ``unknown`` so a caller can
    keep the score as a candidate instead of accidentally comparing unlike
    experiments.
    """

    metadata = score.metadata if isinstance(score.metadata, Mapping) else {}

    def dimension(name: str, *values: Any) -> str:
        for value in values:
            if value is not None and str(value).strip():
                return normalize_key(str(value).strip())
        fallback = metadata.get(name)
        if fallback is not None and str(fallback).strip():
            return normalize_key(str(fallback).strip())
        return "unknown"

    return {
        "benchmark": dimension("benchmark", score.benchmark_id),
        "dataset": dimension("dataset", score.dataset_id),
        "dataset_version": dimension("dataset_version", score.dataset_version),
        "split": dimension("split", score.split),
        "metric": dimension("metric", score.metric_id),
        "metric_definition": dimension(
            "metric_definition",
            metadata.get("metric_definition_version"),
            metadata.get("metric_definition"),
        ),
        "direction": dimension("direction", score.direction),
        "unit": dimension("unit", score.unit),
        "preprocessing": dimension("preprocessing"),
        "sample_scope": dimension("sample_scope"),
        "aggregation": dimension("aggregation"),
        "evaluation_protocol": dimension("evaluation_protocol", score.evaluation_protocol),
        "evaluation_code_ref": dimension("evaluation_code_ref"),
    }


def _score_protocol_fingerprint(score: ResearchScore) -> str:
    fields = _score_protocol_fields(score)
    canonical = "|".join(f"{name}={fields[name]}" for name in sorted(fields))
    return sha256(canonical.encode("utf-8")).hexdigest()


def _ensure_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)



__all__ = [
    "ResearchBaseline",
    "ResearchBenchmark",
    "ResearchDataset",
    "ResearchMetric",
    "ResearchSOTAClaim",
    "ResearchScore",
]
