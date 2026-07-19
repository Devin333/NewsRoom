from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from framework.harness.control_plane.errors import HarnessValidationError
from framework.shared.json import stable_json_dumps, to_jsonable
from framework.shared.time import format_datetime, utc_now


class ContextSegmentType(StrEnum):
    GLOBAL_POLICY = "global_policy"
    WORKFLOW = "workflow"
    WORKER_CONTRACT = "worker_contract"
    RUN_STATE = "run_state"
    EVIDENCE_MEMORY = "evidence_memory"
    CURRENT_TASK = "current_task"


class ContextCompressionLevel(StrEnum):
    C0_RAW = "c0_raw"
    C1_CANONICAL_RECORD = "c1_canonical_record"
    C2_STEP_SUMMARY = "c2_step_summary"
    C3_RUN_ROLLING_SUMMARY = "c3_run_rolling_summary"
    C4_LONG_TERM_MEMORY = "c4_long_term_memory"


class ContextCacheScope(StrEnum):
    STABLE_PREFIX = "stable_prefix"
    DYNAMIC_TAIL = "dynamic_tail"


CONTEXT_SEGMENT_ORDER: tuple[ContextSegmentType, ...] = (
    ContextSegmentType.GLOBAL_POLICY,
    ContextSegmentType.WORKFLOW,
    ContextSegmentType.WORKER_CONTRACT,
    ContextSegmentType.RUN_STATE,
    ContextSegmentType.EVIDENCE_MEMORY,
    ContextSegmentType.CURRENT_TASK,
)

NON_COMPRESSIBLE_SEGMENT_TYPES = frozenset(
    {
        ContextSegmentType.GLOBAL_POLICY,
        ContextSegmentType.WORKFLOW,
        ContextSegmentType.WORKER_CONTRACT,
    }
)

CONTROL_PLANE_PRESERVED_FIELDS = frozenset(
    {
        "global_policy",
        "route_table",
        "input_schema",
        "output_schema",
        "forbidden_fields",
        "quality_gates",
        "gate_definition",
        "tool_allowlist",
        "memory_namespace_policy",
        "skill_promotion_policy",
        "source_refs",
        "artifact_refs",
        "budget",
    }
)


@dataclass(frozen=True)
class ContextSegment:
    segment_id: str
    segment_type: ContextSegmentType | str
    content_ref: str
    summary: str
    token_estimate: int
    compression_level: ContextCompressionLevel | str = ContextCompressionLevel.C1_CANONICAL_RECORD
    provenance_refs: tuple[str, ...] = ()
    cache_scope: ContextCacheScope | str = ContextCacheScope.DYNAMIC_TAIL
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not str(self.segment_id).strip():
            raise HarnessValidationError("segment_id is required")
        if not str(self.content_ref).strip():
            raise HarnessValidationError("content_ref is required")
        if self.token_estimate < 0:
            raise HarnessValidationError("token_estimate must not be negative")
        object.__setattr__(self, "segment_id", str(self.segment_id))
        object.__setattr__(self, "segment_type", ContextSegmentType(self.segment_type))
        object.__setattr__(self, "content_ref", str(self.content_ref))
        object.__setattr__(self, "summary", str(self.summary))
        object.__setattr__(self, "compression_level", ContextCompressionLevel(self.compression_level))
        object.__setattr__(self, "provenance_refs", tuple(str(ref) for ref in self.provenance_refs))
        object.__setattr__(self, "cache_scope", ContextCacheScope(self.cache_scope))
        object.__setattr__(self, "metadata", dict(self.metadata))

    def to_dict(self) -> dict[str, Any]:
        return {
            "segment_id": self.segment_id,
            "segment_type": self.segment_type.value,
            "content_ref": self.content_ref,
            "summary": self.summary,
            "token_estimate": self.token_estimate,
            "compression_level": self.compression_level.value,
            "provenance_refs": list(self.provenance_refs),
            "cache_scope": self.cache_scope.value,
            "metadata": to_jsonable(self.metadata),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ContextSegment":
        payload = _context_payload(value, "ContextSegment")
        try:
            segment = cls(
                segment_id=payload.pop("segment_id"),
                segment_type=payload.pop("segment_type"),
                content_ref=payload.pop("content_ref"),
                summary=payload.pop("summary"),
                token_estimate=payload.pop("token_estimate"),
                compression_level=payload.pop(
                    "compression_level",
                    ContextCompressionLevel.C1_CANONICAL_RECORD,
                ),
                provenance_refs=_context_text_sequence(
                    payload.pop("provenance_refs", ()),
                    "ContextSegment.provenance_refs",
                ),
                cache_scope=payload.pop(
                    "cache_scope",
                    ContextCacheScope.DYNAMIC_TAIL,
                ),
                metadata=_context_mapping_value(
                    payload.pop("metadata", {}),
                    "ContextSegment.metadata",
                ),
            )
        except KeyError as exc:
            raise HarnessValidationError(
                f"ContextSegment field is required: {exc.args[0]}"
            ) from exc
        _reject_context_fields(payload, "ContextSegment")
        return segment


@dataclass(frozen=True)
class ContextBudget:
    max_input_tokens: int
    max_output_tokens: int
    max_context_segments: int
    max_evidence_items: int
    max_memory_items: int
    max_artifact_refs: int
    reserved_output_tokens: int = 0
    compression_threshold: float = 0.8
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for field_name in (
            "max_input_tokens",
            "max_output_tokens",
            "max_context_segments",
            "max_evidence_items",
            "max_memory_items",
            "max_artifact_refs",
            "reserved_output_tokens",
        ):
            value = getattr(self, field_name)
            if not isinstance(value, int) or value < 0:
                raise HarnessValidationError(f"{field_name} must be a non-negative integer")
        if self.max_input_tokens <= 0 or self.max_output_tokens <= 0:
            raise HarnessValidationError("max_input_tokens and max_output_tokens must be greater than zero")
        if not 0 < self.compression_threshold <= 1:
            raise HarnessValidationError("compression_threshold must be between 0 and 1")
        object.__setattr__(self, "metadata", dict(self.metadata))

    @classmethod
    def safe_default(cls) -> "ContextBudget":
        return cls(
            max_input_tokens=4096,
            max_output_tokens=1024,
            max_context_segments=6,
            max_evidence_items=8,
            max_memory_items=6,
            max_artifact_refs=12,
            reserved_output_tokens=512,
            compression_threshold=0.8,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "max_input_tokens": self.max_input_tokens,
            "max_output_tokens": self.max_output_tokens,
            "max_context_segments": self.max_context_segments,
            "max_evidence_items": self.max_evidence_items,
            "max_memory_items": self.max_memory_items,
            "max_artifact_refs": self.max_artifact_refs,
            "reserved_output_tokens": self.reserved_output_tokens,
            "compression_threshold": self.compression_threshold,
            "metadata": to_jsonable(self.metadata),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ContextBudget":
        payload = _context_payload(value, "ContextBudget")
        try:
            budget = cls(
                max_input_tokens=payload.pop("max_input_tokens"),
                max_output_tokens=payload.pop("max_output_tokens"),
                max_context_segments=payload.pop("max_context_segments"),
                max_evidence_items=payload.pop("max_evidence_items"),
                max_memory_items=payload.pop("max_memory_items"),
                max_artifact_refs=payload.pop("max_artifact_refs"),
                reserved_output_tokens=payload.pop("reserved_output_tokens", 0),
                compression_threshold=payload.pop("compression_threshold", 0.8),
                metadata=_context_mapping_value(
                    payload.pop("metadata", {}),
                    "ContextBudget.metadata",
                ),
            )
        except KeyError as exc:
            raise HarnessValidationError(
                f"ContextBudget field is required: {exc.args[0]}"
            ) from exc
        _reject_context_fields(payload, "ContextBudget")
        return budget


@dataclass(frozen=True)
class ContextCachePolicy:
    cache_enabled: bool
    stable_prefix_segments: tuple[str, ...]
    dynamic_tail_segments: tuple[str, ...]
    cache_key: str
    provider_hint: str | None = None
    ttl_hint: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not str(self.cache_key).strip():
            raise HarnessValidationError("cache_key is required")
        if self.ttl_hint is not None and self.ttl_hint < 0:
            raise HarnessValidationError("ttl_hint must not be negative")
        object.__setattr__(self, "stable_prefix_segments", tuple(str(item) for item in self.stable_prefix_segments))
        object.__setattr__(self, "dynamic_tail_segments", tuple(str(item) for item in self.dynamic_tail_segments))
        object.__setattr__(self, "metadata", dict(self.metadata))

    def to_dict(self) -> dict[str, Any]:
        return {
            "cache_enabled": self.cache_enabled,
            "stable_prefix_segments": list(self.stable_prefix_segments),
            "dynamic_tail_segments": list(self.dynamic_tail_segments),
            "cache_key": self.cache_key,
            "provider_hint": self.provider_hint,
            "ttl_hint": self.ttl_hint,
            "metadata": to_jsonable(self.metadata),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ContextCachePolicy":
        payload = _context_payload(value, "ContextCachePolicy")
        try:
            policy = cls(
                cache_enabled=payload.pop("cache_enabled"),
                stable_prefix_segments=_context_text_sequence(
                    payload.pop("stable_prefix_segments"),
                    "ContextCachePolicy.stable_prefix_segments",
                ),
                dynamic_tail_segments=_context_text_sequence(
                    payload.pop("dynamic_tail_segments"),
                    "ContextCachePolicy.dynamic_tail_segments",
                ),
                cache_key=payload.pop("cache_key"),
                provider_hint=payload.pop("provider_hint", None),
                ttl_hint=payload.pop("ttl_hint", None),
                metadata=_context_mapping_value(
                    payload.pop("metadata", {}),
                    "ContextCachePolicy.metadata",
                ),
            )
        except KeyError as exc:
            raise HarnessValidationError(
                f"ContextCachePolicy field is required: {exc.args[0]}"
            ) from exc
        _reject_context_fields(payload, "ContextCachePolicy")
        return policy


@dataclass(frozen=True)
class ContextEnvelope:
    envelope_id: str
    run_id: str | None = None
    workflow_id: str | None = None
    step_id: str | None = None
    phase: str | None = None
    worker_id: str | None = None
    worker_type: str | None = None
    segments: tuple[ContextSegment, ...] = ()
    budget: ContextBudget | None = None
    cache_policy: ContextCachePolicy | None = None
    snapshot_ref: str | None = None
    stable_prefix: dict[str, Any] = field(default_factory=dict)
    dynamic_tail: dict[str, Any] = field(default_factory=dict)
    artifact_refs: tuple[str, ...] = ()
    memory_refs: tuple[str, ...] = ()
    evidence_refs: tuple[str, ...] = ()
    token_estimate: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not str(self.envelope_id).strip():
            raise HarnessValidationError("envelope_id is required")
        if self.token_estimate < 0:
            raise HarnessValidationError("token_estimate must not be negative")
        if self.budget is not None and not isinstance(self.budget, ContextBudget):
            raise HarnessValidationError("budget must be ContextBudget")
        if self.cache_policy is not None and not isinstance(self.cache_policy, ContextCachePolicy):
            raise HarnessValidationError("cache_policy must be ContextCachePolicy")
        if not all(isinstance(segment, ContextSegment) for segment in self.segments):
            raise HarnessValidationError("segments must be ContextSegment values")
        stable_json_dumps(self.stable_prefix)
        stable_json_dumps(self.dynamic_tail)
        object.__setattr__(self, "envelope_id", str(self.envelope_id))
        object.__setattr__(self, "segments", tuple(self.segments))
        object.__setattr__(self, "stable_prefix", dict(self.stable_prefix))
        object.__setattr__(self, "dynamic_tail", dict(self.dynamic_tail))
        object.__setattr__(self, "artifact_refs", tuple(str(ref) for ref in self.artifact_refs))
        object.__setattr__(self, "memory_refs", tuple(str(ref) for ref in self.memory_refs))
        object.__setattr__(self, "evidence_refs", tuple(str(ref) for ref in self.evidence_refs))
        object.__setattr__(self, "metadata", dict(self.metadata))

    def to_dict(self) -> dict[str, Any]:
        return {
            "envelope_id": self.envelope_id,
            "run_id": self.run_id,
            "workflow_id": self.workflow_id,
            "step_id": self.step_id,
            "phase": self.phase,
            "worker_id": self.worker_id,
            "worker_type": self.worker_type,
            "segments": [segment.to_dict() for segment in self.segments],
            "budget": self.budget.to_dict() if self.budget else None,
            "cache_policy": self.cache_policy.to_dict() if self.cache_policy else None,
            "snapshot_ref": self.snapshot_ref,
            "stable_prefix": to_jsonable(self.stable_prefix),
            "dynamic_tail": to_jsonable(self.dynamic_tail),
            "artifact_refs": list(self.artifact_refs),
            "memory_refs": list(self.memory_refs),
            "evidence_refs": list(self.evidence_refs),
            "token_estimate": self.token_estimate,
            "metadata": to_jsonable(self.metadata),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ContextEnvelope":
        payload = _context_payload(value, "ContextEnvelope")
        raw_segments = payload.pop("segments", ())
        if not isinstance(raw_segments, (list, tuple)):
            raise HarnessValidationError("ContextEnvelope segments must be a list")
        raw_budget = payload.pop("budget", None)
        raw_cache_policy = payload.pop("cache_policy", None)
        try:
            envelope = cls(
                envelope_id=payload.pop("envelope_id"),
                run_id=payload.pop("run_id", None),
                workflow_id=payload.pop("workflow_id", None),
                step_id=payload.pop("step_id", None),
                phase=payload.pop("phase", None),
                worker_id=payload.pop("worker_id", None),
                worker_type=payload.pop("worker_type", None),
                segments=tuple(
                    ContextSegment.from_dict(segment) for segment in raw_segments
                ),
                budget=(
                    ContextBudget.from_dict(raw_budget)
                    if raw_budget is not None
                    else None
                ),
                cache_policy=(
                    ContextCachePolicy.from_dict(raw_cache_policy)
                    if raw_cache_policy is not None
                    else None
                ),
                snapshot_ref=payload.pop("snapshot_ref", None),
                stable_prefix=_context_mapping_value(
                    payload.pop("stable_prefix", {}),
                    "ContextEnvelope.stable_prefix",
                ),
                dynamic_tail=_context_mapping_value(
                    payload.pop("dynamic_tail", {}),
                    "ContextEnvelope.dynamic_tail",
                ),
                artifact_refs=_context_text_sequence(
                    payload.pop("artifact_refs", ()),
                    "ContextEnvelope.artifact_refs",
                ),
                memory_refs=_context_text_sequence(
                    payload.pop("memory_refs", ()),
                    "ContextEnvelope.memory_refs",
                ),
                evidence_refs=_context_text_sequence(
                    payload.pop("evidence_refs", ()),
                    "ContextEnvelope.evidence_refs",
                ),
                token_estimate=payload.pop("token_estimate", 0),
                metadata=_context_mapping_value(
                    payload.pop("metadata", {}),
                    "ContextEnvelope.metadata",
                ),
            )
        except KeyError as exc:
            raise HarnessValidationError(
                f"ContextEnvelope field is required: {exc.args[0]}"
            ) from exc
        _reject_context_fields(payload, "ContextEnvelope")
        return envelope


@dataclass(frozen=True)
class ContextSnapshot:
    snapshot_id: str
    envelope_id: str
    refs: tuple[str, ...]
    token_estimate: int
    cache_key: str
    checksum: str
    run_id: str | None = None
    step_id: str | None = None
    phase: str | None = None
    segment_refs: tuple[str, ...] = ()
    assembled_prompt_ref: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not str(self.snapshot_id).strip():
            raise HarnessValidationError("snapshot_id is required")
        if not str(self.envelope_id).strip():
            raise HarnessValidationError("envelope_id is required")
        if not self.refs:
            raise HarnessValidationError("ContextSnapshot must store refs instead of large payloads")
        if self.token_estimate < 0:
            raise HarnessValidationError("token_estimate must not be negative")
        if not str(self.cache_key).strip():
            raise HarnessValidationError("cache_key is required")
        if not str(self.checksum).strip():
            raise HarnessValidationError("checksum is required")
        object.__setattr__(self, "refs", tuple(str(ref) for ref in self.refs))
        object.__setattr__(self, "segment_refs", tuple(str(ref) for ref in self.segment_refs))
        object.__setattr__(self, "metadata", dict(self.metadata))

    def to_dict(self) -> dict[str, Any]:
        return {
            "snapshot_id": self.snapshot_id,
            "envelope_id": self.envelope_id,
            "run_id": self.run_id,
            "step_id": self.step_id,
            "phase": self.phase,
            "segment_refs": list(self.segment_refs),
            "assembled_prompt_ref": self.assembled_prompt_ref,
            "refs": list(self.refs),
            "token_estimate": self.token_estimate,
            "cache_key": self.cache_key,
            "checksum": self.checksum,
            "metadata": to_jsonable(self.metadata),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ContextSnapshot":
        payload = _context_payload(value, "ContextSnapshot")
        try:
            snapshot = cls(
                snapshot_id=payload.pop("snapshot_id"),
                envelope_id=payload.pop("envelope_id"),
                refs=_context_text_sequence(
                    payload.pop("refs"),
                    "ContextSnapshot.refs",
                ),
                token_estimate=payload.pop("token_estimate"),
                cache_key=payload.pop("cache_key"),
                checksum=payload.pop("checksum"),
                run_id=payload.pop("run_id", None),
                step_id=payload.pop("step_id", None),
                phase=payload.pop("phase", None),
                segment_refs=_context_text_sequence(
                    payload.pop("segment_refs", ()),
                    "ContextSnapshot.segment_refs",
                ),
                assembled_prompt_ref=payload.pop("assembled_prompt_ref", None),
                metadata=_context_mapping_value(
                    payload.pop("metadata", {}),
                    "ContextSnapshot.metadata",
                ),
            )
        except KeyError as exc:
            raise HarnessValidationError(
                f"ContextSnapshot field is required: {exc.args[0]}"
            ) from exc
        _reject_context_fields(payload, "ContextSnapshot")
        return snapshot


@dataclass(frozen=True)
class ContextCompressionSummary:
    summary_id: str
    source_envelope_id: str
    summary_ref: str
    token_estimate_before: int
    token_estimate_after: int
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not str(self.summary_id).strip():
            raise HarnessValidationError("summary_id is required")
        if not str(self.source_envelope_id).strip():
            raise HarnessValidationError("source_envelope_id is required")
        if not str(self.summary_ref).strip():
            raise HarnessValidationError("summary_ref is required")
        if self.token_estimate_before < 0 or self.token_estimate_after < 0:
            raise HarnessValidationError("token estimates must not be negative")
        object.__setattr__(self, "metadata", dict(self.metadata))

    def to_dict(self) -> dict[str, Any]:
        return {
            "summary_id": self.summary_id,
            "source_envelope_id": self.source_envelope_id,
            "summary_ref": self.summary_ref,
            "token_estimate_before": self.token_estimate_before,
            "token_estimate_after": self.token_estimate_after,
            "metadata": to_jsonable(self.metadata),
        }


@dataclass(frozen=True)
class CompressionRecord:
    compression_id: str
    run_id: str
    source_ref: str
    source_level: ContextCompressionLevel | str
    target_level: ContextCompressionLevel | str
    summary_ref: str
    lost_fields: tuple[str, ...] = ()
    preserved_refs: tuple[str, ...] = ()
    gate_results: tuple[dict[str, Any], ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: Any = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        for field_name in ("compression_id", "run_id", "source_ref", "summary_ref"):
            if not str(getattr(self, field_name)).strip():
                raise HarnessValidationError(f"{field_name} is required")
        object.__setattr__(self, "source_level", ContextCompressionLevel(self.source_level))
        object.__setattr__(self, "target_level", ContextCompressionLevel(self.target_level))
        object.__setattr__(self, "lost_fields", tuple(str(field) for field in self.lost_fields))
        object.__setattr__(self, "preserved_refs", tuple(str(ref) for ref in self.preserved_refs))
        object.__setattr__(self, "gate_results", tuple(dict(result) for result in self.gate_results))
        object.__setattr__(self, "metadata", dict(self.metadata))

    def to_dict(self) -> dict[str, Any]:
        return {
            "compression_id": self.compression_id,
            "run_id": self.run_id,
            "source_ref": self.source_ref,
            "source_level": self.source_level.value,
            "target_level": self.target_level.value,
            "summary_ref": self.summary_ref,
            "lost_fields": list(self.lost_fields),
            "preserved_refs": list(self.preserved_refs),
            "gate_results": to_jsonable(list(self.gate_results)),
            "metadata": to_jsonable(self.metadata),
            "created_at": format_datetime(self.created_at),
        }


def _context_payload(value: Mapping[str, Any], model: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise HarnessValidationError(f"{model} payload must be an object")
    return dict(value)


def _reject_context_fields(payload: Mapping[str, Any], model: str) -> None:
    if payload:
        raise HarnessValidationError(
            f"{model} payload contains unsupported fields: "
            + ", ".join(sorted(payload))
        )


def _context_mapping_value(value: Any, field_name: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise HarnessValidationError(f"{field_name} must be an object")
    return dict(value)


def _context_text_sequence(value: Any, field_name: str) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)) or any(
        not isinstance(item, str) for item in value
    ):
        raise HarnessValidationError(f"{field_name} must be a list of strings")
    return tuple(value)


__all__ = [
    "CONTEXT_SEGMENT_ORDER",
    "CONTROL_PLANE_PRESERVED_FIELDS",
    "NON_COMPRESSIBLE_SEGMENT_TYPES",
    "CompressionRecord",
    "ContextBudget",
    "ContextCachePolicy",
    "ContextCacheScope",
    "ContextCompressionLevel",
    "ContextCompressionSummary",
    "ContextEnvelope",
    "ContextSegment",
    "ContextSegmentType",
    "ContextSnapshot",
]
