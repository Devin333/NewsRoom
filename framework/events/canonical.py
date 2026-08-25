from __future__ import annotations

import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from hashlib import sha256
from types import MappingProxyType
from typing import Any, TypeAlias

from framework.events.errors import (
    EventCanonicalizationError,
    EventExtensionLimitError,
    EventIdentityCollisionError,
    EventIntegrityError,
    EventPayloadTooLargeError,
    EventTimeError,
)
from framework.events.schema.security import SecurityClassification
from framework.shared.json import stable_json_dumps
from framework.shared.graph_identity import GraphExecutionIdentity, GraphRunIdentity
from framework.shared.time import ensure_utc, format_datetime, parse_datetime


ENVELOPE_SCHEMA_V2 = "newsroom.event-envelope/v2"
DEFAULT_CONTENT_TYPE = "application/json"
DEFAULT_MAX_INLINE_PAYLOAD_BYTES = 64 * 1024
DEFAULT_MAX_EXTENSION_COUNT = 32
DEFAULT_MAX_EXTENSION_BYTES = 8 * 1024

_CHECKSUM_PATTERN = re.compile(r"sha256:[0-9a-f]{64}\Z")
_BUSINESS_CONTEXT_FIELDS = frozenset(
    {
        "run_id",
        "graph_id",
        "graph_version",
        "graph_ref",
        "graph_checksum",
        "execution_identity",
        "stage_id",
        "node_instance_id",
        "task_id",
        "agent_id",
        "tool_call_id",
        "request_id",
    }
)
_HISTORY_ONLY_NULL_CONTEXT_FIELDS = frozenset({"step_id", "workflow_id"})
_PRODUCER_FIELDS = frozenset({"component", "version", "instance_id"})
_TRACE_FIELDS = frozenset(
    {
        "trace_id",
        "span_id",
        "trace_flags",
        "tracestate",
        "is_remote",
        "parent_span_id",
    }
)
_PAYLOAD_REFERENCE_FIELDS = frozenset(
    {"uri", "expected_checksum", "content_type", "size_bytes"}
)
_CANDIDATE_FIELDS = frozenset(
    {
        "envelope_schema",
        "event_id",
        "event_type",
        "data_schema",
        "source",
        "subject",
        "occurred_at",
        "stream_id",
        "correlation_id",
        "causation_id",
        "business_context",
        "producer",
        "trace",
        "tenant_id",
        "security_classification",
        "content_type",
        "payload",
        "payload_ref",
        "extensions",
        "content_checksum",
    }
)
_STORED_EVENT_FIELDS = _CANDIDATE_FIELDS | frozenset(
    {"observed_at", "stream_sequence", "record_checksum"}
)

CanonicalScalar: TypeAlias = None | bool | int | float | str
CanonicalValue: TypeAlias = CanonicalScalar | Mapping[str, "CanonicalValue"] | tuple["CanonicalValue", ...]


@dataclass(frozen=True)
class BusinessContext:
    run_id: str | None = None
    graph_id: str | None = None
    graph_version: str | None = None
    graph_ref: str | None = None
    graph_checksum: str | None = None
    execution_identity: GraphExecutionIdentity | None = None
    stage_id: str | None = None
    node_instance_id: str | None = None
    task_id: str | None = None
    agent_id: str | None = None
    tool_call_id: str | None = None
    request_id: str | None = None

    def __post_init__(self) -> None:
        for field_name in (
            "run_id",
            "graph_id",
            "graph_version",
            "graph_ref",
            "graph_checksum",
            "stage_id",
            "node_instance_id",
            "task_id",
            "agent_id",
            "tool_call_id",
            "request_id",
        ):
            object.__setattr__(self, field_name, _optional_text(getattr(self, field_name)))
        execution_identity = self.execution_identity
        if execution_identity is not None and not isinstance(
            execution_identity, GraphExecutionIdentity
        ):
            if not isinstance(execution_identity, Mapping):
                raise EventCanonicalizationError(
                    "business_context execution_identity must be an object"
                )
            try:
                execution_identity = GraphExecutionIdentity.from_dict(execution_identity)
            except (TypeError, ValueError) as exc:
                raise EventCanonicalizationError(
                    "business_context execution_identity is invalid"
                ) from exc
        if execution_identity is not None:
            if self.run_id is not None and self.run_id != execution_identity.run_id:
                raise EventCanonicalizationError(
                    "business_context execution identity run_id conflicts"
                )
            object.__setattr__(self, "execution_identity", execution_identity)
            for field_name in (
                "run_id",
                "graph_id",
                "graph_version",
                "graph_ref",
                "graph_checksum",
            ):
                object.__setattr__(self, field_name, getattr(execution_identity, field_name))
            if self.stage_id is not None and self.stage_id != execution_identity.node_id:
                raise EventCanonicalizationError(
                    "business_context stage_id conflicts with execution identity"
                )
            if self.node_instance_id is not None and self.node_instance_id != execution_identity.node_instance_id:
                raise EventCanonicalizationError(
                    "business_context node_instance_id conflicts with execution identity"
                )
            object.__setattr__(self, "stage_id", execution_identity.node_id)
            object.__setattr__(self, "node_instance_id", execution_identity.node_instance_id)
        else:
            object.__setattr__(self, "execution_identity", None)
        graph_fields = (
            self.graph_id,
            self.graph_version,
            self.graph_ref,
            self.graph_checksum,
        )
        if any(value is not None for value in graph_fields):
            if self.run_id is None or not all(value is not None for value in graph_fields):
                raise EventCanonicalizationError(
                    "business_context Graph identity must contain run_id and all Graph fields"
                )
            try:
                graph_identity = GraphRunIdentity(
                    run_id=self.run_id,
                    graph_id=self.graph_id,
                    graph_version=self.graph_version,
                    graph_ref=self.graph_ref,
                    graph_checksum=self.graph_checksum,
                )
            except (TypeError, ValueError) as exc:
                raise EventCanonicalizationError(
                    "business_context Graph identity is invalid"
                ) from exc
            for field_name in (
                "run_id",
                "graph_id",
                "graph_version",
                "graph_ref",
                "graph_checksum",
            ):
                object.__setattr__(self, field_name, getattr(graph_identity, field_name))

    @property
    def graph_identity(self) -> GraphRunIdentity | None:
        if self.graph_id is None:
            return None
        return GraphRunIdentity(
            run_id=self.run_id,
            graph_id=self.graph_id,
            graph_version=self.graph_version,
            graph_ref=self.graph_ref,
            graph_checksum=self.graph_checksum,
        )

    @property
    def physical_identity(self) -> GraphExecutionIdentity | None:
        return self.execution_identity

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "run_id": self.run_id,
            "graph_id": self.graph_id,
            "graph_version": self.graph_version,
            "graph_ref": self.graph_ref,
            "graph_checksum": self.graph_checksum,
            "stage_id": self.stage_id,
            "node_instance_id": self.node_instance_id,
            "task_id": self.task_id,
            "agent_id": self.agent_id,
            "tool_call_id": self.tool_call_id,
            "request_id": self.request_id,
        }
        if self.execution_identity is not None:
            payload["execution_identity"] = self.execution_identity.to_dict()
        return payload

    @classmethod
    def from_dict(cls, value: Mapping[str, Any] | None) -> BusinessContext:
        if value is None:
            payload: dict[str, Any] = {}
        elif isinstance(value, Mapping):
            payload = dict(value)
        else:
            raise EventCanonicalizationError("event business_context must be an object")
        _reject_unknown_fields(payload, _BUSINESS_CONTEXT_FIELDS, "business_context")
        return cls(
            run_id=payload.get("run_id"),
            graph_id=payload.get("graph_id"),
            graph_version=payload.get("graph_version"),
            graph_ref=payload.get("graph_ref"),
            graph_checksum=payload.get("graph_checksum"),
            execution_identity=payload.get("execution_identity"),
            stage_id=payload.get("stage_id"),
            node_instance_id=payload.get("node_instance_id"),
            task_id=payload.get("task_id"),
            agent_id=payload.get("agent_id"),
            tool_call_id=payload.get("tool_call_id"),
            request_id=payload.get("request_id"),
        )


@dataclass(frozen=True)
class ProducerIdentity:
    component: str
    version: str | None = None
    instance_id: str | None = None

    def __post_init__(self) -> None:
        component = _required_text(self.component, "producer component")
        object.__setattr__(self, "component", component)
        object.__setattr__(self, "version", _optional_text(self.version))
        object.__setattr__(self, "instance_id", _optional_text(self.instance_id))

    def to_dict(self) -> dict[str, str | None]:
        return {
            "component": self.component,
            "version": self.version,
            "instance_id": self.instance_id,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> ProducerIdentity:
        _reject_unknown_fields(value, _PRODUCER_FIELDS, "producer")
        return cls(
            component=value.get("component"),
            version=value.get("version"),
            instance_id=value.get("instance_id"),
        )


@dataclass(frozen=True)
class TraceBlock:
    trace_id: str
    span_id: str
    trace_flags: str = "00"
    tracestate: str | None = None
    is_remote: bool = False
    parent_span_id: str | None = None

    def __post_init__(self) -> None:
        trace_id = _required_text(self.trace_id, "trace_id")
        span_id = _required_text(self.span_id, "span_id")
        trace_flags = _required_text(self.trace_flags, "trace_flags")
        if not isinstance(self.is_remote, bool):
            raise EventCanonicalizationError("trace is_remote must be a boolean")
        object.__setattr__(self, "trace_id", trace_id)
        object.__setattr__(self, "span_id", span_id)
        object.__setattr__(self, "trace_flags", trace_flags)
        object.__setattr__(self, "tracestate", _optional_text(self.tracestate))
        object.__setattr__(self, "parent_span_id", _optional_text(self.parent_span_id))
        object.__setattr__(self, "is_remote", self.is_remote)

    def to_dict(self) -> dict[str, Any]:
        return {
            "trace_id": self.trace_id,
            "span_id": self.span_id,
            "trace_flags": self.trace_flags,
            "tracestate": self.tracestate,
            "is_remote": self.is_remote,
            "parent_span_id": self.parent_span_id,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> TraceBlock:
        _reject_unknown_fields(value, _TRACE_FIELDS, "trace")
        return cls(
            trace_id=value.get("trace_id"),
            span_id=value.get("span_id"),
            trace_flags=value.get("trace_flags"),
            tracestate=value.get("tracestate"),
            is_remote=value.get("is_remote"),
            parent_span_id=value.get("parent_span_id"),
        )


@dataclass(frozen=True)
class PayloadReference:
    uri: str
    expected_checksum: str
    content_type: str = DEFAULT_CONTENT_TYPE
    size_bytes: int | None = None

    def __post_init__(self) -> None:
        uri = _required_text(self.uri, "payload reference uri")
        checksum = _required_text(
            self.expected_checksum,
            "payload reference checksum",
        ).lower()
        content_type = _required_text(
            self.content_type,
            "payload reference content_type",
        )
        _validate_checksum(checksum, field_name="payload reference checksum")
        size_bytes = self.size_bytes
        if size_bytes is not None:
            if isinstance(size_bytes, bool) or not isinstance(size_bytes, int):
                raise EventCanonicalizationError(
                    "payload reference size_bytes must be an integer"
                )
            if size_bytes < 0:
                raise ValueError("payload reference size_bytes must be non-negative")
        object.__setattr__(self, "uri", uri)
        object.__setattr__(self, "expected_checksum", checksum)
        object.__setattr__(self, "content_type", content_type)
        object.__setattr__(self, "size_bytes", size_bytes)

    def to_dict(self) -> dict[str, Any]:
        return {
            "uri": self.uri,
            "expected_checksum": self.expected_checksum,
            "content_type": self.content_type,
            "size_bytes": self.size_bytes,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> PayloadReference:
        _reject_unknown_fields(value, _PAYLOAD_REFERENCE_FIELDS, "payload_ref")
        return cls(
            uri=value.get("uri"),
            expected_checksum=value.get("expected_checksum"),
            content_type=value.get("content_type"),
            size_bytes=value.get("size_bytes"),
        )


@dataclass(frozen=True)
class EventCandidate:
    """Canonical post-security, pre-storage acceptance projection."""

    event_id: str
    event_type: str
    data_schema: str
    source: str
    occurred_at: datetime
    stream_id: str
    business_context: BusinessContext
    producer: ProducerIdentity
    subject: str | None = None
    correlation_id: str | None = None
    causation_id: str | None = None
    trace: TraceBlock | None = None
    tenant_id: str | None = None
    security_classification: SecurityClassification | str = SecurityClassification.INTERNAL
    content_type: str = DEFAULT_CONTENT_TYPE
    payload: Mapping[str, Any] | None = field(default_factory=dict)
    payload_ref: PayloadReference | None = None
    extensions: Mapping[str, Any] = field(default_factory=dict)
    envelope_schema: str = ENVELOPE_SCHEMA_V2
    legacy_business_context: Mapping[str, Any] | None = field(
        default=None,
        repr=False,
    )
    max_inline_payload_bytes: int = field(
        default=DEFAULT_MAX_INLINE_PAYLOAD_BYTES,
        repr=False,
        compare=False,
    )
    max_extension_count: int = field(
        default=DEFAULT_MAX_EXTENSION_COUNT,
        repr=False,
        compare=False,
    )
    max_extension_bytes: int = field(
        default=DEFAULT_MAX_EXTENSION_BYTES,
        repr=False,
        compare=False,
    )
    content_checksum: str = field(init=False)

    def __post_init__(self) -> None:
        for field_name in (
            "event_id",
            "event_type",
            "data_schema",
            "source",
            "stream_id",
            "content_type",
            "envelope_schema",
        ):
            value = _required_text(getattr(self, field_name), field_name)
            object.__setattr__(self, field_name, value)

        if self.envelope_schema != ENVELOPE_SCHEMA_V2:
            raise ValueError(f"unsupported envelope_schema: {self.envelope_schema}")
        if self.max_inline_payload_bytes <= 0:
            raise ValueError("max_inline_payload_bytes must be positive")
        if self.max_extension_count <= 0:
            raise ValueError("max_extension_count must be positive")
        if self.max_extension_bytes <= 0:
            raise ValueError("max_extension_bytes must be positive")
        object.__setattr__(self, "occurred_at", _required_time(self.occurred_at, "occurred_at"))
        object.__setattr__(self, "subject", _optional_text(self.subject))
        object.__setattr__(self, "correlation_id", _optional_text(self.correlation_id))
        object.__setattr__(self, "causation_id", _optional_text(self.causation_id))
        object.__setattr__(self, "tenant_id", _optional_text(self.tenant_id))
        object.__setattr__(
            self,
            "security_classification",
            SecurityClassification(self.security_classification),
        )

        if not isinstance(self.business_context, BusinessContext):
            object.__setattr__(
                self,
                "business_context",
                BusinessContext.from_dict(self.business_context),
            )
        legacy_business_context = self.legacy_business_context
        if legacy_business_context is not None:
            if not isinstance(legacy_business_context, Mapping):
                raise EventCanonicalizationError(
                    "history business_context must be an object"
                )
            legacy_business_context = dict(legacy_business_context)
            _reject_unknown_fields(
                legacy_business_context,
                _BUSINESS_CONTEXT_FIELDS | _HISTORY_ONLY_NULL_CONTEXT_FIELDS,
                "history business_context",
            )
            if any(
                legacy_business_context.get(field_name) is not None
                for field_name in _HISTORY_ONLY_NULL_CONTEXT_FIELDS
                if field_name in legacy_business_context
            ):
                raise EventCanonicalizationError(
                    "history business_context legacy identity must be null"
                )
            normalized_legacy_context = normalize_canonical_json(
                legacy_business_context,
                path="$.history.business_context",
            )
            if not isinstance(normalized_legacy_context, Mapping):
                raise EventCanonicalizationError(
                    "history business_context must be an object"
                )
            object.__setattr__(
                self,
                "legacy_business_context",
                normalized_legacy_context,
            )
        if not isinstance(self.producer, ProducerIdentity):
            object.__setattr__(self, "producer", ProducerIdentity.from_dict(self.producer))
        if self.trace is not None and not isinstance(self.trace, TraceBlock):
            object.__setattr__(self, "trace", TraceBlock.from_dict(self.trace))
        if self.payload_ref is not None and not isinstance(self.payload_ref, PayloadReference):
            object.__setattr__(
                self,
                "payload_ref",
                PayloadReference.from_dict(self.payload_ref),
            )

        if (
            self.payload_ref is not None
            and self.payload_ref.content_type != self.content_type
        ):
            raise ValueError("payload_ref content_type must match event content_type")

        if self.payload is not None and self.payload_ref is not None:
            raise ValueError("payload and payload_ref are mutually exclusive")
        if self.payload is None and self.payload_ref is None:
            raise ValueError("payload or payload_ref is required")

        canonical_payload: Mapping[str, CanonicalValue] | None
        if self.payload is None:
            canonical_payload = None
        else:
            normalized_payload = normalize_canonical_json(self.payload, path="$.payload")
            if not isinstance(normalized_payload, Mapping):
                raise EventCanonicalizationError("event payload must be an object")
            canonical_payload = normalized_payload
            payload_size = len(canonical_json_bytes(canonical_payload))
            if payload_size > self.max_inline_payload_bytes:
                raise EventPayloadTooLargeError(
                    "inline event payload exceeds configured byte limit"
                )
        object.__setattr__(self, "payload", canonical_payload)

        normalized_extensions = normalize_canonical_json(
            self.extensions,
            path="$.extensions",
        )
        if not isinstance(normalized_extensions, Mapping):
            raise EventCanonicalizationError("event extensions must be an object")
        if len(normalized_extensions) > self.max_extension_count:
            raise EventExtensionLimitError("event extension count exceeds configured limit")
        extension_size = len(canonical_json_bytes(normalized_extensions))
        if extension_size > self.max_extension_bytes:
            raise EventExtensionLimitError("event extensions exceed configured byte limit")
        object.__setattr__(self, "extensions", normalized_extensions)

        object.__setattr__(
            self,
            "content_checksum",
            checksum_for(self.content_projection()),
        )

    def content_projection(self) -> dict[str, Any]:
        return {
            "envelope_schema": self.envelope_schema,
            "event_id": self.event_id,
            "event_type": self.event_type,
            "data_schema": self.data_schema,
            "source": self.source,
            "subject": self.subject,
            "occurred_at": format_datetime(self.occurred_at),
            "stream_id": self.stream_id,
            "correlation_id": self.correlation_id,
            "causation_id": self.causation_id,
            "business_context": (
                thaw_canonical_json(self.legacy_business_context)
                if self.legacy_business_context is not None
                else self.business_context.to_dict()
            ),
            "producer": self.producer.to_dict(),
            "trace": self.trace.to_dict() if self.trace is not None else None,
            "tenant_id": self.tenant_id,
            "security_classification": self.security_classification.value,
            "content_type": self.content_type,
            "payload": thaw_canonical_json(self.payload) if self.payload is not None else None,
            "payload_ref": self.payload_ref.to_dict() if self.payload_ref is not None else None,
            "extensions": thaw_canonical_json(self.extensions),
        }

    def to_dict(self) -> dict[str, Any]:
        return {**self.content_projection(), "content_checksum": self.content_checksum}

    @classmethod
    def from_dict(
        cls,
        value: Mapping[str, Any],
        *,
        verify_checksum: bool = True,
        _allow_stored_fields: bool = False,
        _allow_history_only_context: bool = False,
    ) -> EventCandidate:
        _reject_unknown_fields(
            value,
            _STORED_EVENT_FIELDS if _allow_stored_fields else _CANDIDATE_FIELDS,
            "event",
        )
        occurred_at = parse_datetime(value.get("occurred_at"))
        if occurred_at is None:
            raise EventTimeError("event occurred_at is required")
        payload_ref_raw = value.get("payload_ref")
        raw_business_context = _required_mapping(
            value.get("business_context"),
            "business_context",
        )
        legacy_business_context = _history_only_context_projection(
            raw_business_context,
            allow_history_only=_allow_history_only_context,
        )
        business_context = (
            {
                key: item
                for key, item in raw_business_context.items()
                if key not in _HISTORY_ONLY_NULL_CONTEXT_FIELDS
            }
            if legacy_business_context is not None
            else raw_business_context
        )
        candidate = cls(
            envelope_schema=value.get("envelope_schema"),
            event_id=value.get("event_id"),
            event_type=value.get("event_type"),
            data_schema=value.get("data_schema"),
            source=value.get("source"),
            subject=value.get("subject"),
            occurred_at=occurred_at,
            stream_id=value.get("stream_id"),
            correlation_id=value.get("correlation_id"),
            causation_id=value.get("causation_id"),
            business_context=BusinessContext.from_dict(business_context),
            producer=ProducerIdentity.from_dict(
                _required_mapping(value.get("producer"), "producer")
            ),
            trace=(
                TraceBlock.from_dict(_required_mapping(value.get("trace"), "trace"))
                if value.get("trace") is not None
                else None
            ),
            tenant_id=value.get("tenant_id"),
            security_classification=_required_text(
                value.get("security_classification"),
                "security_classification",
            ),
            content_type=_required_text(value.get("content_type"), "content_type"),
            payload=(
                _required_mapping(value.get("payload"), "payload")
                if value.get("payload") is not None
                else None
            ),
            payload_ref=(
                PayloadReference.from_dict(
                    _required_mapping(payload_ref_raw, "payload_ref")
                )
                if payload_ref_raw is not None
                else None
            ),
            extensions=_mapping_or_empty(value.get("extensions")),
            legacy_business_context=legacy_business_context,
        )
        if verify_checksum:
            supplied = str(value.get("content_checksum") or "").lower()
            if supplied != candidate.content_checksum:
                raise EventIntegrityError("event content checksum does not match")
        return candidate


@dataclass(frozen=True)
class StoredEvent:
    """One immutable event accepted by a durable store."""

    candidate: EventCandidate
    observed_at: datetime
    stream_sequence: int
    record_checksum: str = field(init=False)

    def __post_init__(self) -> None:
        if not isinstance(self.candidate, EventCandidate):
            object.__setattr__(
                self,
                "candidate",
                EventCandidate.from_dict(self.candidate),
            )
        object.__setattr__(self, "observed_at", _required_time(self.observed_at, "observed_at"))
        if isinstance(self.stream_sequence, bool) or not isinstance(
            self.stream_sequence,
            int,
        ):
            raise EventCanonicalizationError("stream_sequence must be an integer")
        sequence = self.stream_sequence
        if sequence <= 0:
            raise ValueError("stream_sequence must be 1-based and positive")
        object.__setattr__(self, "stream_sequence", sequence)
        object.__setattr__(self, "record_checksum", checksum_for(self.record_projection()))

    @property
    def envelope_schema(self) -> str:
        return self.candidate.envelope_schema

    @property
    def event_id(self) -> str:
        return self.candidate.event_id

    @property
    def event_type(self) -> str:
        return self.candidate.event_type

    @property
    def data_schema(self) -> str:
        return self.candidate.data_schema

    @property
    def source(self) -> str:
        return self.candidate.source

    @property
    def subject(self) -> str | None:
        return self.candidate.subject

    @property
    def occurred_at(self) -> datetime:
        return self.candidate.occurred_at

    @property
    def stream_id(self) -> str:
        return self.candidate.stream_id

    @property
    def correlation_id(self) -> str | None:
        return self.candidate.correlation_id

    @property
    def causation_id(self) -> str | None:
        return self.candidate.causation_id

    @property
    def business_context(self) -> BusinessContext:
        return self.candidate.business_context

    @property
    def producer(self) -> ProducerIdentity:
        return self.candidate.producer

    @property
    def trace(self) -> TraceBlock | None:
        return self.candidate.trace

    @property
    def tenant_id(self) -> str | None:
        return self.candidate.tenant_id

    @property
    def security_classification(self) -> SecurityClassification:
        return self.candidate.security_classification

    @property
    def content_type(self) -> str:
        return self.candidate.content_type

    @property
    def payload(self) -> Mapping[str, CanonicalValue] | None:
        return self.candidate.payload

    @property
    def payload_ref(self) -> PayloadReference | None:
        return self.candidate.payload_ref

    @property
    def extensions(self) -> Mapping[str, CanonicalValue]:
        return self.candidate.extensions

    @property
    def content_checksum(self) -> str:
        return self.candidate.content_checksum

    def record_projection(self) -> dict[str, Any]:
        return {
            **self.candidate.to_dict(),
            "observed_at": format_datetime(self.observed_at),
            "stream_sequence": self.stream_sequence,
        }

    def to_dict(self) -> dict[str, Any]:
        return {**self.record_projection(), "record_checksum": self.record_checksum}

    def verify_integrity(self) -> None:
        expected_content = checksum_for(self.candidate.content_projection())
        if expected_content != self.content_checksum:
            raise EventIntegrityError("event content checksum does not match")
        expected_record = checksum_for(self.record_projection())
        if expected_record != self.record_checksum:
            raise EventIntegrityError("event record checksum does not match")

    @classmethod
    def from_dict(
        cls,
        value: Mapping[str, Any],
        *,
        verify_checksum: bool = True,
    ) -> StoredEvent:
        _reject_unknown_fields(value, _STORED_EVENT_FIELDS, "stored_event")
        observed_at = parse_datetime(value.get("observed_at"))
        if observed_at is None:
            raise EventTimeError("event observed_at is required")
        candidate = EventCandidate.from_dict(
            value,
            verify_checksum=verify_checksum,
            _allow_stored_fields=True,
            _allow_history_only_context=_is_history_only_source_event(value),
        )
        stored = cls(
            candidate=candidate,
            observed_at=observed_at,
            stream_sequence=value.get("stream_sequence"),
        )
        if verify_checksum:
            supplied = str(value.get("record_checksum") or "").lower()
            if supplied != stored.record_checksum:
                raise EventIntegrityError("event record checksum does not match")
        return stored


def _is_history_only_source_event(value: Mapping[str, Any]) -> bool:
    event_type = value.get("event_type")
    data_schema = value.get("data_schema")
    return (
        isinstance(event_type, str)
        and event_type.startswith("source_")
        and isinstance(data_schema, str)
        and data_schema.startswith("io.newsroom.source.")
    )


def _history_only_context_projection(
    value: Mapping[str, Any],
    *,
    allow_history_only: bool,
) -> Mapping[str, Any] | None:
    if not _HISTORY_ONLY_NULL_CONTEXT_FIELDS.intersection(value):
        return None
    if not allow_history_only:
        return None
    if any(
        value.get(field_name) is not None
        for field_name in _HISTORY_ONLY_NULL_CONTEXT_FIELDS
        if field_name in value
    ):
        raise EventCanonicalizationError(
            "history source event legacy context identity must be null"
        )
    return dict(value)


def normalize_canonical_json(value: Any, *, path: str = "$") -> CanonicalValue:
    """Validate, detach, and recursively freeze the supported JSON contract."""

    if value is None or isinstance(value, (bool, str)):
        return value
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise EventCanonicalizationError(f"non-finite number at {path}")
        if value == 0:
            return 0
        return value
    if isinstance(value, Mapping):
        normalized: dict[str, CanonicalValue] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise EventCanonicalizationError(f"non-string object key at {path}")
            normalized[key] = normalize_canonical_json(
                item,
                path=f"{path}.{key}" if path else key,
            )
        return MappingProxyType(normalized)
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return tuple(
            normalize_canonical_json(item, path=f"{path}[{index}]")
            for index, item in enumerate(value)
        )
    raise EventCanonicalizationError(
        f"unsupported canonical JSON value at {path}: {type(value).__name__}"
    )


def thaw_canonical_json(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): thaw_canonical_json(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [thaw_canonical_json(item) for item in value]
    return value


def canonical_json_bytes(value: Any) -> bytes:
    return stable_json_dumps(thaw_canonical_json(value)).encode("utf-8")


def checksum_for(value: Any) -> str:
    return f"sha256:{sha256(canonical_json_bytes(value)).hexdigest()}"


def assert_same_event_identity(
    existing: StoredEvent,
    candidate: EventCandidate,
) -> None:
    if existing.event_id != candidate.event_id:
        raise ValueError("event ids do not match")
    if existing.content_checksum != candidate.content_checksum:
        raise EventIdentityCollisionError(candidate.event_id)


def _required_time(value: datetime, field_name: str) -> datetime:
    if not isinstance(value, datetime):
        raise EventTimeError(f"event {field_name} is required")
    if value.tzinfo is None or value.utcoffset() is None:
        raise EventTimeError(f"event {field_name} must be timezone-aware")
    return ensure_utc(value)


def _validate_checksum(value: str, *, field_name: str) -> None:
    if _CHECKSUM_PATTERN.fullmatch(str(value)) is None:
        raise ValueError(f"{field_name} must be sha256:<64 lowercase hex>")


def _required_mapping(value: Any, field_name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise EventCanonicalizationError(f"event {field_name} must be an object")
    return value


def _mapping_or_empty(value: Any) -> Mapping[str, Any]:
    if value is None:
        return {}
    return _required_mapping(value, "mapping")


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise EventCanonicalizationError("optional canonical text must be a string")
    text = value.strip()
    return text or None


def _required_text(value: Any, field_name: str) -> str:
    if not isinstance(value, str):
        raise EventCanonicalizationError(f"{field_name} must be a string")
    text = value.strip()
    if not text:
        raise ValueError(f"{field_name} is required")
    return text


def _reject_unknown_fields(
    value: Mapping[str, Any],
    allowed: frozenset[str],
    field_name: str,
) -> None:
    unknown = sorted(str(key) for key in value if key not in allowed)
    if unknown:
        raise EventCanonicalizationError(
            f"unknown canonical {field_name} field(s): {', '.join(unknown)}"
        )
