from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from enum import StrEnum
from typing import Any

from framework.harness.control_plane.errors import HarnessValidationError
from framework.harness.graph.versioning import (
    GRAPH_ONLY_NORMALIZED_HARNESS_GRAPH_SCHEMA,
    HARNESS_CONDITION_POLICY_VERSION,
    HARNESS_GRAPH_ONLY_COMPILER_VERSION,
)
from framework.shared.json import stable_json_dumps, to_jsonable
from framework.shared.time import format_datetime, utc_now
from framework.shared.graph_identity import (
    GraphExecutionIdentity,
    GraphRunIdentity,
    GraphStageIdentity,
)


class ContextSegmentType(StrEnum):
    GLOBAL_POLICY = "global_policy"
    GRAPH = "graph"
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
    ContextSegmentType.GRAPH,
    ContextSegmentType.WORKER_CONTRACT,
    ContextSegmentType.RUN_STATE,
    ContextSegmentType.EVIDENCE_MEMORY,
    ContextSegmentType.CURRENT_TASK,
)

NON_COMPRESSIBLE_SEGMENT_TYPES = frozenset(
    {
        ContextSegmentType.GLOBAL_POLICY,
        ContextSegmentType.GRAPH,
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

CONTEXT_ENVELOPE_SCHEMA_V2 = "newsroom.context-envelope/v2"
CONTEXT_SNAPSHOT_SCHEMA_V2 = "newsroom.context-snapshot/v2"
CONTEXT_GRAPH_TASK_PLAN_STAGE_IDENTITY_SCHEMA_V2 = (
    "newsroom.harness-task-plan-stage-identity/v2"
)

_CONTEXT_CHECKSUM_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")
_CONTEXT_EXACT_REFERENCE_PATTERN = re.compile(
    r"(?P<identifier>[A-Za-z0-9][A-Za-z0-9._:/+-]*)@"
    r"(?P<version>[A-Za-z0-9][A-Za-z0-9._+-]*)\Z"
)
_CONTEXT_MOVING_VERSION_ALIASES = frozenset(
    {"current", "default", "latest", "stable"}
)

_GRAPH_CONTEXT_ENVELOPE_FIELDS = frozenset(
    {
        "schema_version",
        "envelope_id",
        "graph_identity",
        "task_execution_identity",
        "phase",
        "worker_id",
        "worker_type",
        "segments",
        "budget",
        "cache_policy",
        "snapshot_ref",
        "stable_prefix",
        "dynamic_tail",
        "artifact_refs",
        "memory_refs",
        "evidence_refs",
        "token_estimate",
        "metadata",
        "checksum",
    }
)

_GRAPH_CONTEXT_SNAPSHOT_FIELDS = frozenset(
    {
        "schema_version",
        "snapshot_id",
        "envelope_id",
        "envelope_checksum",
        "graph_identity",
        "task_execution_identity",
        "phase",
        "segment_refs",
        "assembled_prompt_ref",
        "refs",
        "token_estimate",
        "cache_key",
        "checksum",
        "metadata",
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
class ContextGraphIdentity:
    """Frozen Graph and stage identity for a Graph-only context."""

    run_id: str
    graph_id: str
    graph_version: str
    graph_ref: str
    graph_schema_version: str
    compiler_version: str
    condition_policy_version: str
    graph_checksum: str
    stage_id: str
    stage_binding_checksum: str
    stage_identity_schema: str
    stage_identity_checksum: str
    node_id: str | None = None
    node_instance_id: str | None = None
    activity_id: str | None = None
    activity_attempt: int | None = None

    def __post_init__(self) -> None:
        for field_name in (
            "run_id",
            "graph_id",
            "graph_version",
            "graph_schema_version",
            "compiler_version",
            "condition_policy_version",
            "stage_id",
            "stage_identity_schema",
        ):
            object.__setattr__(
                self,
                field_name,
                _context_required_text(getattr(self, field_name), field_name),
            )
        physical_values = (
            self.node_id,
            self.node_instance_id,
            self.activity_id,
            self.activity_attempt,
        )
        if any(value is not None for value in physical_values):
            if any(value is None for value in physical_values):
                raise HarnessValidationError(
                    "Graph context physical identity must be complete",
                    code="context_graph_identity_mismatch",
                )
            for field_name in ("node_id", "node_instance_id", "activity_id"):
                object.__setattr__(
                    self,
                    field_name,
                    _context_required_text(getattr(self, field_name), field_name),
                )
            if (
                isinstance(self.activity_attempt, bool)
                or not isinstance(self.activity_attempt, int)
                or self.activity_attempt < 1
            ):
                raise HarnessValidationError(
                    "activity_attempt must be a positive integer",
                    code="context_graph_identity_mismatch",
                )
        graph_ref = _context_required_text(self.graph_ref, "graph_ref")
        reference_match = _CONTEXT_EXACT_REFERENCE_PATTERN.fullmatch(graph_ref)
        if (
            reference_match is None
            or reference_match.group("version").casefold()
            in _CONTEXT_MOVING_VERSION_ALIASES
            or graph_ref != f"{self.graph_id}@{self.graph_version}"
        ):
            raise HarnessValidationError(
                "Graph context requires an exact ref matching its Graph identity",
                code="context_graph_identity_mismatch",
            )
        if self.graph_schema_version != GRAPH_ONLY_NORMALIZED_HARNESS_GRAPH_SCHEMA:
            raise HarnessValidationError(
                "Graph context uses an unsupported normalized Graph schema",
                code="context_graph_identity_schema_mismatch",
                details={"graph_schema_version": self.graph_schema_version},
            )
        if self.compiler_version != HARNESS_GRAPH_ONLY_COMPILER_VERSION:
            raise HarnessValidationError(
                "Graph context uses an unsupported compiler version",
                code="context_graph_identity_schema_mismatch",
                details={"compiler_version": self.compiler_version},
            )
        if self.condition_policy_version != HARNESS_CONDITION_POLICY_VERSION:
            raise HarnessValidationError(
                "Graph context uses an unsupported condition policy version",
                code="context_graph_identity_schema_mismatch",
                details={
                    "condition_policy_version": self.condition_policy_version,
                },
            )
        if self.stage_identity_schema != CONTEXT_GRAPH_TASK_PLAN_STAGE_IDENTITY_SCHEMA_V2:
            raise HarnessValidationError(
                "Graph context uses an unsupported TaskPlan stage identity schema",
                code="context_graph_identity_schema_mismatch",
                details={"stage_identity_schema": self.stage_identity_schema},
            )
        for field_name in (
            "graph_checksum",
            "stage_binding_checksum",
            "stage_identity_checksum",
        ):
            object.__setattr__(
                self,
                field_name,
                _context_checksum(getattr(self, field_name), field_name),
            )
        expected_stage_identity_checksum = _context_checksum_for(
            self.stage_identity_checksum_projection()
        )
        if self.stage_identity_checksum != expected_stage_identity_checksum:
            raise HarnessValidationError(
                "Graph context stage identity checksum does not match its identity",
                code="context_graph_identity_checksum_mismatch",
            )
        object.__setattr__(self, "graph_ref", graph_ref)

    def stage_identity_checksum_projection(self) -> dict[str, Any]:
        return {
            "schema_version": self.stage_identity_schema,
            "run_id": self.run_id,
            "graph_schema_version": self.graph_schema_version,
            "compiler_version": self.compiler_version,
            "condition_policy_version": self.condition_policy_version,
            "graph_id": self.graph_id,
            "graph_version": self.graph_version,
            "graph_checksum": self.graph_checksum,
            "stage_id": self.stage_id,
            "stage_binding_checksum": self.stage_binding_checksum,
            "graph_ref": self.graph_ref,
        }

    @property
    def has_physical_activity(self) -> bool:
        """Whether this context is bound to one concrete activity attempt."""

        return self.activity_id is not None

    def with_physical_activity(
        self,
        *,
        node_id: str,
        node_instance_id: str,
        activity_id: str,
        activity_attempt: int,
    ) -> "ContextGraphIdentity":
        """Bind an exact physical activity without changing stage authority."""

        if node_id != self.stage_id:
            raise HarnessValidationError(
                "Graph activity node does not match the context stage",
                code="context_graph_identity_mismatch",
            )
        if self.has_physical_activity:
            current = (
                self.node_id,
                self.node_instance_id,
                self.activity_id,
                self.activity_attempt,
            )
            requested = (node_id, node_instance_id, activity_id, activity_attempt)
            if current != requested:
                raise HarnessValidationError(
                    "Graph context physical identity cannot be rebound",
                    code="context_graph_identity_mismatch",
                )
            return self
        return replace(
            self,
            node_id=node_id,
            node_instance_id=node_instance_id,
            activity_id=activity_id,
            activity_attempt=activity_attempt,
        )

    def to_graph_run_identity(self) -> GraphRunIdentity:
        """Convert the context's immutable outer identity to the canonical carrier."""

        return GraphRunIdentity(
            run_id=self.run_id,
            graph_id=self.graph_id,
            graph_version=self.graph_version,
            graph_ref=self.graph_ref,
            graph_checksum=self.graph_checksum,
        )

    def to_graph_stage_identity(self) -> GraphStageIdentity:
        """Convert this context to the canonical stage identity carrier."""

        if not self.node_id or not self.node_instance_id:
            raise HarnessValidationError(
                "Graph stage identity requires node and node-instance fields",
                code="context_graph_identity_mismatch",
            )
        return GraphStageIdentity(
            run_id=self.run_id,
            graph_id=self.graph_id,
            graph_version=self.graph_version,
            graph_ref=self.graph_ref,
            graph_checksum=self.graph_checksum,
            node_id=self.node_id,
            node_instance_id=self.node_instance_id,
        )

    def to_graph_execution_identity(self) -> GraphExecutionIdentity:
        """Convert a physical context to the canonical execution identity carrier."""

        if not self.has_physical_activity:
            raise HarnessValidationError(
                "Graph execution identity requires a physical activity",
                code="context_graph_execution_identity_required",
            )
        return GraphExecutionIdentity(
            run_id=self.run_id,
            graph_id=self.graph_id,
            graph_version=self.graph_version,
            graph_ref=self.graph_ref,
            graph_checksum=self.graph_checksum,
            node_id=self.node_id,
            node_instance_id=self.node_instance_id,
            activity_id=self.activity_id,
            attempt=self.activity_attempt,
        )

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "run_id": self.run_id,
            "graph_id": self.graph_id,
            "graph_version": self.graph_version,
            "graph_ref": self.graph_ref,
            "graph_schema_version": self.graph_schema_version,
            "compiler_version": self.compiler_version,
            "condition_policy_version": self.condition_policy_version,
            "graph_checksum": self.graph_checksum,
            "stage_id": self.stage_id,
            "stage_binding_checksum": self.stage_binding_checksum,
            "stage_identity_schema": self.stage_identity_schema,
            "stage_identity_checksum": self.stage_identity_checksum,
        }
        if self.node_id is not None:
            payload.update(
                {
                    "node_id": self.node_id,
                    "node_instance_id": self.node_instance_id,
                    "activity_id": self.activity_id,
                    "activity_attempt": self.activity_attempt,
                }
            )
        return payload

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ContextGraphIdentity":
        payload = _context_payload(value, "ContextGraphIdentity")
        physical_fields = frozenset(
            {"node_id", "node_instance_id", "activity_id", "activity_attempt"}
        )
        present_physical_fields = physical_fields.intersection(payload)
        if present_physical_fields and present_physical_fields != physical_fields:
            raise HarnessValidationError(
                "ContextGraphIdentity physical fields do not match its schema",
                code="context_schema_fields_invalid",
                details={
                    "missing": sorted(physical_fields - present_physical_fields),
                    "unexpected": [],
                },
            )
        _require_context_fields(
            payload,
            required=frozenset(
                {
                    "run_id",
                    "graph_id",
                    "graph_version",
                    "graph_ref",
                    "graph_schema_version",
                    "compiler_version",
                    "condition_policy_version",
                    "graph_checksum",
                    "stage_id",
                    "stage_binding_checksum",
                    "stage_identity_schema",
                    "stage_identity_checksum",
                }
            )
            | present_physical_fields,
            model="ContextGraphIdentity",
        )
        return cls(**payload)


@dataclass(frozen=True)
class ContextTaskExecutionIdentity:
    """Exact TaskPlan attempt identity carried only by TaskPlan execution context."""

    plan_id: str
    plan_version: int
    plan_checksum: str
    task_id: str
    task_definition_checksum: str
    task_instance_id: str
    attempt: int

    def __post_init__(self) -> None:
        for field_name in (
            "plan_id",
            "task_id",
            "task_instance_id",
        ):
            object.__setattr__(
                self,
                field_name,
                _context_required_text(getattr(self, field_name), field_name),
            )
        for field_name in (
            "plan_checksum",
            "task_definition_checksum",
        ):
            object.__setattr__(
                self,
                field_name,
                _context_checksum(getattr(self, field_name), field_name),
            )
        for field_name in ("plan_version", "attempt"):
            value = getattr(self, field_name)
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise HarnessValidationError(
                    f"{field_name} must be a positive integer",
                    code="context_graph_identity_mismatch",
                )

    def to_dict(self) -> dict[str, Any]:
        return {
            "plan_id": self.plan_id,
            "plan_version": self.plan_version,
            "plan_checksum": self.plan_checksum,
            "task_id": self.task_id,
            "task_definition_checksum": self.task_definition_checksum,
            "task_instance_id": self.task_instance_id,
            "attempt": self.attempt,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ContextTaskExecutionIdentity":
        payload = _context_payload(value, "ContextTaskExecutionIdentity")
        _require_context_fields(
            payload,
            required=frozenset(
                {
                    "plan_id",
                    "plan_version",
                    "plan_checksum",
                    "task_id",
                    "task_definition_checksum",
                    "task_instance_id",
                    "attempt",
                }
            ),
            model="ContextTaskExecutionIdentity",
        )
        return cls(**payload)


@dataclass(frozen=True)
class ContextEnvelope:
    envelope_id: str
    run_id: str | None = None
    stage_id: str | None = None
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
    schema_version: str = CONTEXT_ENVELOPE_SCHEMA_V2
    graph_identity: ContextGraphIdentity | None = None
    task_execution_identity: ContextTaskExecutionIdentity | None = None
    checksum: str | None = None

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
        if self.schema_version != CONTEXT_ENVELOPE_SCHEMA_V2:
            raise HarnessValidationError(
                "unsupported ContextEnvelope schema",
                code="context_envelope_schema_unsupported",
                details={"schema_version": str(self.schema_version)},
            )
        if not isinstance(self.graph_identity, ContextGraphIdentity):
            raise HarnessValidationError(
                "Graph-only ContextEnvelope requires Graph identity",
                code="context_envelope_identity_schema_mismatch",
            )
        if (
            self.task_execution_identity is not None
            and not isinstance(
                self.task_execution_identity,
                ContextTaskExecutionIdentity,
            )
        ):
            raise HarnessValidationError(
                "Graph-only ContextEnvelope task identity is invalid",
                code="context_envelope_identity_schema_mismatch",
            )
        if self.run_id != self.graph_identity.run_id:
            raise HarnessValidationError(
                "Graph context run_id does not match its identity",
                code="context_graph_identity_mismatch",
            )
        if self.stage_id != self.graph_identity.stage_id:
            raise HarnessValidationError(
                "Graph context stage_id does not match its stage identity",
                code="context_graph_identity_mismatch",
            )
        for field_name in ("phase", "worker_id", "worker_type"):
            object.__setattr__(
                self,
                field_name,
                _context_required_text(getattr(self, field_name), field_name),
            )
        if isinstance(self.token_estimate, bool) or not isinstance(self.token_estimate, int):
            raise HarnessValidationError(
                "Graph-only ContextEnvelope token_estimate must be an integer",
                code="context_envelope_identity_schema_mismatch",
            )
        expected_checksum = _context_checksum_for(self._graph_checksum_projection())
        if self.checksum is not None and self.checksum != expected_checksum:
            raise HarnessValidationError(
                "ContextEnvelope checksum does not match canonical content",
                code="context_envelope_checksum_mismatch",
            )
        object.__setattr__(self, "checksum", expected_checksum)

    @property
    def is_graph_only(self) -> bool:
        return True

    @classmethod
    def for_graph(
        cls,
        *,
        envelope_id: str,
        graph_identity: ContextGraphIdentity,
        task_execution_identity: ContextTaskExecutionIdentity | None = None,
        phase: str,
        worker_id: str,
        worker_type: str,
        segments: tuple[ContextSegment, ...] = (),
        budget: ContextBudget | None = None,
        cache_policy: ContextCachePolicy | None = None,
        snapshot_ref: str | None = None,
        stable_prefix: dict[str, Any] | None = None,
        dynamic_tail: dict[str, Any] | None = None,
        artifact_refs: tuple[str, ...] = (),
        memory_refs: tuple[str, ...] = (),
        evidence_refs: tuple[str, ...] = (),
        token_estimate: int = 0,
        metadata: dict[str, Any] | None = None,
    ) -> "ContextEnvelope":
        if not isinstance(graph_identity, ContextGraphIdentity):
            raise TypeError("graph_identity must be ContextGraphIdentity")
        return cls(
            envelope_id=envelope_id,
            run_id=graph_identity.run_id,
            stage_id=graph_identity.stage_id,
            phase=phase,
            worker_id=worker_id,
            worker_type=worker_type,
            segments=segments,
            budget=budget,
            cache_policy=cache_policy,
            snapshot_ref=snapshot_ref,
            stable_prefix=stable_prefix or {},
            dynamic_tail=dynamic_tail or {},
            artifact_refs=artifact_refs,
            memory_refs=memory_refs,
            evidence_refs=evidence_refs,
            token_estimate=token_estimate,
            metadata=metadata or {},
            schema_version=CONTEXT_ENVELOPE_SCHEMA_V2,
            graph_identity=graph_identity,
            task_execution_identity=task_execution_identity,
        )

    def matches_graph_identity(self, identity: ContextGraphIdentity) -> bool:
        return (
            isinstance(identity, ContextGraphIdentity)
            and self.graph_identity == identity
        )

    def matches_task_execution_identity(
        self,
        identity: ContextTaskExecutionIdentity,
    ) -> bool:
        return (
            isinstance(identity, ContextTaskExecutionIdentity)
            and self.is_graph_only
            and self.task_execution_identity == identity
        )

    def bind_cache_policy(self, policy: ContextCachePolicy) -> "ContextEnvelope":
        if not isinstance(policy, ContextCachePolicy):
            raise TypeError("policy must be ContextCachePolicy")
        return replace(
            self,
            cache_policy=policy,
            checksum=None,
        )

    def bind_snapshot_ref(self, snapshot_ref: str) -> "ContextEnvelope":
        reference = _context_required_text(snapshot_ref, "snapshot_ref")
        return replace(
            self,
            snapshot_ref=reference,
            checksum=None,
        )

    def matches_graph_fields(self, expected: Mapping[str, Any]) -> bool:
        if self.graph_identity is None:
            return False
        actual = self.graph_identity.to_dict()
        if self.task_execution_identity is not None:
            actual.update(self.task_execution_identity.to_dict())
        aliases = {
            "parent_run_id": "run_id",
            "stage_id": "stage_id",
            "task_id": "task_id",
            "task_instance_id": "task_instance_id",
            "attempt": "attempt",
        }
        return all(actual.get(aliases.get(name, name)) == value for name, value in expected.items())

    def _graph_checksum_projection(self) -> dict[str, Any]:
        if self.graph_identity is None:
            raise HarnessValidationError(
                "ContextEnvelope has no Graph checksum projection",
                code="context_envelope_identity_schema_mismatch",
            )
        return {
            "schema_version": self.schema_version,
            "envelope_id": self.envelope_id,
            "graph_identity": self.graph_identity.to_dict(),
            "task_execution_identity": (
                self.task_execution_identity.to_dict()
                if self.task_execution_identity is not None
                else None
            ),
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

    def to_dict(self) -> dict[str, Any]:
        return {**self._graph_checksum_projection(), "checksum": self.checksum}

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ContextEnvelope":
        payload = _context_payload(value, "ContextEnvelope")
        if payload.get("schema_version") != CONTEXT_ENVELOPE_SCHEMA_V2:
            raise HarnessValidationError(
                "unsupported ContextEnvelope schema",
                code="context_envelope_schema_unsupported",
                details={"schema_version": str(payload.get("schema_version"))},
            )
        return cls._from_graph_dict(payload)

    @classmethod
    def _from_graph_dict(cls, payload: dict[str, Any]) -> "ContextEnvelope":
        _require_context_fields(
            payload,
            required=_GRAPH_CONTEXT_ENVELOPE_FIELDS,
            model="ContextEnvelope",
        )
        if payload.get("schema_version") != CONTEXT_ENVELOPE_SCHEMA_V2:
            raise HarnessValidationError(
                "unsupported ContextEnvelope schema",
                code="context_envelope_schema_unsupported",
                details={"schema_version": str(payload.get("schema_version"))},
            )
        raw_segments = payload["segments"]
        if not isinstance(raw_segments, (list, tuple)):
            raise HarnessValidationError("ContextEnvelope segments must be a list")
        raw_budget = payload["budget"]
        raw_cache_policy = payload["cache_policy"]
        identity = ContextGraphIdentity.from_dict(payload["graph_identity"])
        raw_task_identity = payload["task_execution_identity"]
        task_identity = (
            ContextTaskExecutionIdentity.from_dict(raw_task_identity)
            if raw_task_identity is not None
            else None
        )
        try:
            return cls(
                envelope_id=payload["envelope_id"],
                run_id=identity.run_id,
                stage_id=identity.stage_id,
                phase=payload["phase"],
                worker_id=payload["worker_id"],
                worker_type=payload["worker_type"],
                segments=tuple(ContextSegment.from_dict(segment) for segment in raw_segments),
                budget=ContextBudget.from_dict(raw_budget) if raw_budget is not None else None,
                cache_policy=(
                    ContextCachePolicy.from_dict(raw_cache_policy)
                    if raw_cache_policy is not None
                    else None
                ),
                snapshot_ref=payload["snapshot_ref"],
                stable_prefix=_context_mapping_value(payload["stable_prefix"], "ContextEnvelope.stable_prefix"),
                dynamic_tail=_context_mapping_value(payload["dynamic_tail"], "ContextEnvelope.dynamic_tail"),
                artifact_refs=_context_text_sequence(payload["artifact_refs"], "ContextEnvelope.artifact_refs"),
                memory_refs=_context_text_sequence(payload["memory_refs"], "ContextEnvelope.memory_refs"),
                evidence_refs=_context_text_sequence(payload["evidence_refs"], "ContextEnvelope.evidence_refs"),
                token_estimate=payload["token_estimate"],
                metadata=_context_mapping_value(payload["metadata"], "ContextEnvelope.metadata"),
                schema_version=payload["schema_version"],
                graph_identity=identity,
                task_execution_identity=task_identity,
                checksum=payload["checksum"],
            )
        except KeyError as exc:
            raise HarnessValidationError(
                f"ContextEnvelope field is required: {exc.args[0]}"
            ) from exc


@dataclass(frozen=True)
class ContextSnapshot:
    snapshot_id: str
    envelope_id: str
    refs: tuple[str, ...]
    token_estimate: int
    cache_key: str
    checksum: str
    run_id: str | None = None
    stage_id: str | None = None
    phase: str | None = None
    segment_refs: tuple[str, ...] = ()
    assembled_prompt_ref: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    schema_version: str = CONTEXT_SNAPSHOT_SCHEMA_V2
    graph_identity: ContextGraphIdentity | None = None
    task_execution_identity: ContextTaskExecutionIdentity | None = None
    envelope_checksum: str | None = None

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
        if self.schema_version != CONTEXT_SNAPSHOT_SCHEMA_V2:
            raise HarnessValidationError(
                "unsupported ContextSnapshot schema",
                code="context_snapshot_schema_unsupported",
                details={"schema_version": str(self.schema_version)},
            )
        if not isinstance(self.graph_identity, ContextGraphIdentity):
            raise HarnessValidationError(
                "Graph-only ContextSnapshot requires Graph identity",
                code="context_snapshot_identity_schema_mismatch",
            )
        if (
            self.task_execution_identity is not None
            and not isinstance(
                self.task_execution_identity,
                ContextTaskExecutionIdentity,
            )
        ):
            raise HarnessValidationError(
                "Graph-only ContextSnapshot task identity is invalid",
                code="context_snapshot_identity_schema_mismatch",
            )
        if self.run_id != self.graph_identity.run_id or self.stage_id != self.graph_identity.stage_id:
            raise HarnessValidationError(
                "Graph context snapshot does not match its identity",
                code="context_graph_identity_mismatch",
            )
        object.__setattr__(
            self,
            "phase",
            _context_required_text(self.phase, "phase"),
        )
        if isinstance(self.token_estimate, bool) or not isinstance(self.token_estimate, int):
            raise HarnessValidationError(
                "Graph-only ContextSnapshot token_estimate must be an integer",
                code="context_snapshot_identity_schema_mismatch",
            )
        object.__setattr__(
            self,
            "envelope_checksum",
            _context_checksum(self.envelope_checksum, "envelope_checksum"),
        )
        expected_checksum = _context_checksum_for(self._graph_checksum_projection())
        if self.checksum != expected_checksum:
            raise HarnessValidationError(
                "ContextSnapshot checksum does not match canonical content",
                code="context_snapshot_checksum_mismatch",
            )

    @property
    def is_graph_only(self) -> bool:
        return True

    @classmethod
    def for_graph_envelope(
        cls,
        *,
        snapshot_id: str,
        envelope: ContextEnvelope,
        refs: tuple[str, ...],
        segment_refs: tuple[str, ...],
        assembled_prompt_ref: str | None,
        cache_key: str,
        metadata: dict[str, Any] | None = None,
    ) -> "ContextSnapshot":
        if envelope.graph_identity is None:
            raise HarnessValidationError(
                "Graph context snapshot requires a Graph-only envelope",
                code="context_snapshot_identity_schema_mismatch",
            )
        if envelope.checksum is None:  # pragma: no cover - envelope invariant
            raise AssertionError("Graph-only ContextEnvelope checksum is unavailable")
        snapshot_metadata = metadata or {}
        projection = {
            "schema_version": CONTEXT_SNAPSHOT_SCHEMA_V2,
            "snapshot_id": snapshot_id,
            "envelope_id": envelope.envelope_id,
            "envelope_checksum": envelope.checksum,
            "graph_identity": envelope.graph_identity.to_dict(),
            "task_execution_identity": (
                envelope.task_execution_identity.to_dict()
                if envelope.task_execution_identity is not None
                else None
            ),
            "phase": envelope.phase,
            "segment_refs": list(segment_refs),
            "assembled_prompt_ref": assembled_prompt_ref,
            "refs": list(refs),
            "token_estimate": envelope.token_estimate,
            "cache_key": cache_key,
            "metadata": to_jsonable(snapshot_metadata),
        }
        return cls(
            snapshot_id=snapshot_id,
            envelope_id=envelope.envelope_id,
            refs=refs,
            token_estimate=envelope.token_estimate,
            cache_key=cache_key,
            checksum=_context_checksum_for(projection),
            run_id=envelope.graph_identity.run_id,
            stage_id=envelope.graph_identity.stage_id,
            phase=envelope.phase,
            segment_refs=segment_refs,
            assembled_prompt_ref=assembled_prompt_ref,
            metadata=snapshot_metadata,
            schema_version=CONTEXT_SNAPSHOT_SCHEMA_V2,
            graph_identity=envelope.graph_identity,
            task_execution_identity=envelope.task_execution_identity,
            envelope_checksum=envelope.checksum,
        )

    def _graph_checksum_projection(self) -> dict[str, Any]:
        if self.graph_identity is None:
            raise HarnessValidationError(
                "ContextSnapshot has no Graph checksum projection",
                code="context_snapshot_identity_schema_mismatch",
            )
        return {
            "schema_version": self.schema_version,
            "snapshot_id": self.snapshot_id,
            "envelope_id": self.envelope_id,
            "envelope_checksum": self.envelope_checksum,
            "graph_identity": self.graph_identity.to_dict(),
            "task_execution_identity": (
                self.task_execution_identity.to_dict()
                if self.task_execution_identity is not None
                else None
            ),
            "phase": self.phase,
            "segment_refs": list(self.segment_refs),
            "assembled_prompt_ref": self.assembled_prompt_ref,
            "refs": list(self.refs),
            "token_estimate": self.token_estimate,
            "cache_key": self.cache_key,
            "metadata": to_jsonable(self.metadata),
        }

    def to_dict(self) -> dict[str, Any]:
        return {**self._graph_checksum_projection(), "checksum": self.checksum}

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ContextSnapshot":
        payload = _context_payload(value, "ContextSnapshot")
        if payload.get("schema_version") != CONTEXT_SNAPSHOT_SCHEMA_V2:
            raise HarnessValidationError(
                "unsupported ContextSnapshot schema",
                code="context_snapshot_schema_unsupported",
                details={"schema_version": str(payload.get("schema_version"))},
            )
        return cls._from_graph_dict(payload)

    @classmethod
    def _from_graph_dict(cls, payload: dict[str, Any]) -> "ContextSnapshot":
        _require_context_fields(
            payload,
            required=_GRAPH_CONTEXT_SNAPSHOT_FIELDS,
            model="ContextSnapshot",
        )
        if payload.get("schema_version") != CONTEXT_SNAPSHOT_SCHEMA_V2:
            raise HarnessValidationError(
                "unsupported ContextSnapshot schema",
                code="context_snapshot_schema_unsupported",
                details={"schema_version": str(payload.get("schema_version"))},
            )
        identity = ContextGraphIdentity.from_dict(payload["graph_identity"])
        raw_task_identity = payload["task_execution_identity"]
        task_identity = (
            ContextTaskExecutionIdentity.from_dict(raw_task_identity)
            if raw_task_identity is not None
            else None
        )
        try:
            return cls(
                snapshot_id=payload["snapshot_id"],
                envelope_id=payload["envelope_id"],
                refs=_context_text_sequence(payload["refs"], "ContextSnapshot.refs"),
                token_estimate=payload["token_estimate"],
                cache_key=payload["cache_key"],
                checksum=payload["checksum"],
                run_id=identity.run_id,
                stage_id=identity.stage_id,
                phase=payload["phase"],
                segment_refs=_context_text_sequence(
                    payload["segment_refs"],
                    "ContextSnapshot.segment_refs",
                ),
                assembled_prompt_ref=payload["assembled_prompt_ref"],
                metadata=_context_mapping_value(payload["metadata"], "ContextSnapshot.metadata"),
                schema_version=payload["schema_version"],
                graph_identity=identity,
                task_execution_identity=task_identity,
                envelope_checksum=payload["envelope_checksum"],
            )
        except KeyError as exc:
            raise HarnessValidationError(
                f"ContextSnapshot field is required: {exc.args[0]}"
            ) from exc


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


def _context_required_text(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or value != value.strip() or not value:
        raise HarnessValidationError(
            f"{field_name} must be a non-blank trimmed string",
            code="context_graph_identity_mismatch",
            details={"field": field_name},
        )
    return value


def _context_checksum(value: Any, field_name: str) -> str:
    text = _context_required_text(value, field_name)
    if _CONTEXT_CHECKSUM_PATTERN.fullmatch(text) is None:
        raise HarnessValidationError(
            f"{field_name} must be a canonical sha256 reference",
            code="context_graph_identity_mismatch",
            details={"field": field_name},
        )
    return text


def _context_checksum_for(payload: Mapping[str, Any]) -> str:
    digest = hashlib.sha256(stable_json_dumps(payload).encode()).hexdigest()
    return f"sha256:{digest}"


def _require_context_fields(
    payload: Mapping[str, Any],
    *,
    required: frozenset[str],
    model: str,
) -> None:
    actual = set(payload)
    missing = sorted(required.difference(actual))
    unexpected = sorted(str(name) for name in actual.difference(required))
    if missing or unexpected:
        raise HarnessValidationError(
            f"{model} fields do not match its schema",
            code="context_schema_fields_invalid",
            details={"missing": missing, "unexpected": unexpected},
        )


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
    "CONTEXT_ENVELOPE_SCHEMA_V2",
    "CONTEXT_GRAPH_TASK_PLAN_STAGE_IDENTITY_SCHEMA_V2",
    "CONTEXT_SNAPSHOT_SCHEMA_V2",
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
    "ContextGraphIdentity",
    "ContextSegment",
    "ContextSegmentType",
    "ContextSnapshot",
    "ContextTaskExecutionIdentity",
]
