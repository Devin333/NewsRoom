from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime, timezone as _tz
import re
import secrets
from typing import Any
from uuid import uuid4

from framework.events.canonical import (
    CanonicalValue,
    normalize_canonical_json,
    thaw_canonical_json,
)
from framework.events.errors import EventCanonicalizationError, EventTimeError
from framework.shared.graph_identity import GraphExecutionIdentity
from framework.shared.time import ensure_utc, format_datetime, parse_datetime


UTC = _tz.utc
TRACE_EVENT_SCHEMA_VERSION = "newsroom.trace_event.v1"
TRACE_CONTEXT_SCHEMA_VERSION = "newsroom.trace-context/v2"
TRACE_METADATA_SCHEMA_VERSION = "newsroom.trace-metadata/v1"
REDACTED_TRACE_VALUE = "[REDACTED]"
MAX_TRACESTATE_BYTES = 512

_TRACE_ID_PATTERN = re.compile(r"[0-9a-f]{32}\Z")
_SPAN_ID_PATTERN = re.compile(r"[0-9a-f]{16}\Z")
_TRACE_FLAGS_PATTERN = re.compile(r"[0-9a-f]{2}\Z")
_CAMEL_BOUNDARY_1 = re.compile(r"(.)([A-Z][a-z]+)")
_CAMEL_BOUNDARY_2 = re.compile(r"([a-z0-9])([A-Z])")
_KEY_SEPARATOR = re.compile(r"[^A-Za-z0-9]+")
_TRACE_CONTEXT_FIELDS = frozenset(
    {
        "schema_version",
        "execution_identity",
        "trace_id",
        "span_id",
        "parent_span_id",
        "trace_flags",
        "tracestate",
        "is_remote",
        "agent_id",
        "tool_call_id",
        "memory_operation_id",
        "artifact_id",
        "metadata",
    }
)

# These are exact normalized field names, not substrings. A schema can add
# sensitive paths or explicitly allow one path through TraceRedactionPolicy.
_DEFAULT_CREDENTIAL_KEYS = frozenset(
    {
        "access_token",
        "api_key",
        "api_token",
        "apikey",
        "auth",
        "auth_token",
        "authorization",
        "aws_access_key_id",
        "aws_secret_access_key",
        "aws_session_token",
        "bearer_token",
        "certificate_private_key",
        "client_secret",
        "client_secret_key",
        "connection_string",
        "cookie",
        "credential",
        "credentials",
        "database_password",
        "database_url",
        "dsn",
        "encryption_key",
        "github_token",
        "gitlab_token",
        "id_token",
        "oauth_token",
        "password",
        "passwd",
        "personal_access_token",
        "private_key",
        "proxy_authorization",
        "pwd",
        "refresh_token",
        "sas_token",
        "secret",
        "secret_key",
        "service_account_key",
        "session_token",
        "set_cookie",
        "signing_key",
        "smtp_password",
        "token",
        "webhook_secret",
        "x_api_key",
    }
)


@dataclass(frozen=True, slots=True)
class TraceRedactionPolicy:
    """Exact schema policy for trace metadata, payload, and error projection."""

    schema_id: str = TRACE_METADATA_SCHEMA_VERSION
    credential_keys: frozenset[str] = _DEFAULT_CREDENTIAL_KEYS
    sensitive_paths: frozenset[str] = frozenset()
    allowed_paths: frozenset[str] = frozenset()

    def __post_init__(self) -> None:
        schema_id = _required_str(self.schema_id, "trace redaction schema_id")
        credential_keys = frozenset(
            _normalize_credential_key(key)
            for key in self.credential_keys
            if _normalize_credential_key(key)
        )
        sensitive_paths = _normalize_policy_paths(
            self.sensitive_paths,
            "sensitive_paths",
        )
        allowed_paths = _normalize_policy_paths(self.allowed_paths, "allowed_paths")
        if sensitive_paths & allowed_paths:
            raise ValueError("trace redaction paths cannot be both sensitive and allowed")
        object.__setattr__(self, "schema_id", schema_id)
        object.__setattr__(self, "credential_keys", credential_keys)
        object.__setattr__(self, "sensitive_paths", sensitive_paths)
        object.__setattr__(self, "allowed_paths", allowed_paths)

    def is_sensitive(self, *, key: str, path: str) -> bool:
        if path in self.allowed_paths:
            return False
        return path in self.sensitive_paths or (
            _normalize_credential_key(key) in self.credential_keys
        )


@dataclass(frozen=True, slots=True)
class TraceContext:
    """Business trace context bound to one exact Graph activity attempt.

    W3C transport state is intentionally kept separate in ``W3CSpanContext``.
    A business TraceContext cannot be created without a complete physical
    execution identity, so transport-only propagation uses ``extract_span``.
    """

    execution_identity: GraphExecutionIdentity
    trace_id: str
    span_id: str
    parent_span_id: str | None = None
    agent_id: str | None = None
    tool_call_id: str | None = None
    memory_operation_id: str | None = None
    artifact_id: str | None = None
    metadata: Mapping[str, CanonicalValue] = field(default_factory=dict)
    trace_flags: str = "00"
    tracestate: str | None = None
    is_remote: bool = False
    schema_version: str = TRACE_CONTEXT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not isinstance(self.execution_identity, GraphExecutionIdentity):
            raise TypeError("execution_identity must be GraphExecutionIdentity")
        object.__setattr__(self, "trace_id", _required_str(self.trace_id, "trace_id"))
        object.__setattr__(self, "span_id", _required_str(self.span_id, "span_id"))
        object.__setattr__(
            self,
            "parent_span_id",
            _optional_str(self.parent_span_id, "parent_span_id"),
        )
        for field_name in ("agent_id", "tool_call_id", "memory_operation_id", "artifact_id"):
            object.__setattr__(
                self,
                field_name,
                _optional_str(getattr(self, field_name), field_name),
            )
        trace_flags = _required_str(self.trace_flags, "trace_flags")
        if not is_valid_trace_flags(trace_flags):
            raise ValueError("trace_flags must be two lowercase hexadecimal characters")
        object.__setattr__(self, "trace_flags", trace_flags)
        tracestate = _optional_str(self.tracestate, "tracestate")
        if tracestate is not None:
            if "\r" in tracestate or "\n" in tracestate:
                raise ValueError("tracestate cannot contain line breaks")
            if len(tracestate.encode("utf-8")) > MAX_TRACESTATE_BYTES:
                raise ValueError("tracestate exceeds the W3C byte limit")
        object.__setattr__(self, "tracestate", tracestate)
        if not isinstance(self.is_remote, bool):
            raise TypeError("is_remote must be a boolean")
        if self.schema_version != TRACE_CONTEXT_SCHEMA_VERSION:
            raise ValueError("trace context schema is unsupported")
        object.__setattr__(self, "metadata", _immutable_mapping(self.metadata, "metadata"))

    @property
    def is_w3c_valid(self) -> bool:
        return is_valid_trace_id(self.trace_id) and is_valid_span_id(self.span_id)

    @property
    def is_injectable(self) -> bool:
        return self.is_w3c_valid and is_valid_trace_flags(self.trace_flags)

    @property
    def has_legacy_identifiers(self) -> bool:
        return not self.is_w3c_valid

    @property
    def run_id(self) -> str:
        return self.execution_identity.run_id

    @property
    def graph_id(self) -> str:
        return self.execution_identity.graph_id

    @property
    def graph_version(self) -> str:
        return self.execution_identity.graph_version

    @property
    def graph_ref(self) -> str:
        return self.execution_identity.graph_ref

    @property
    def graph_checksum(self) -> str:
        return self.execution_identity.graph_checksum

    @property
    def graph_identity(self) -> GraphExecutionIdentity:
        return self.execution_identity

    @classmethod
    def root(
        cls,
        *,
        execution_identity: GraphExecutionIdentity,
        trace_id: str | None = None,
        span_id: str | None = None,
        agent_id: str | None = None,
        tool_call_id: str | None = None,
        memory_operation_id: str | None = None,
        artifact_id: str | None = None,
        metadata: Mapping[str, Any] | None = None,
        trace_flags: str = "00",
        tracestate: str | None = None,
        is_remote: bool = False,
    ) -> "TraceContext":
        return cls(
            execution_identity=execution_identity,
            trace_id=trace_id if trace_id is not None else new_trace_id(),
            span_id=span_id if span_id is not None else new_span_id(),
            agent_id=agent_id,
            tool_call_id=tool_call_id,
            memory_operation_id=memory_operation_id,
            artifact_id=artifact_id,
            metadata=metadata or {},
            trace_flags=trace_flags,
            tracestate=tracestate,
            is_remote=is_remote,
        )

    def child(
        self,
        *,
        span_id: str | None = None,
        agent_id: str | None = None,
        tool_call_id: str | None = None,
        memory_operation_id: str | None = None,
        artifact_id: str | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> "TraceContext":
        child_metadata = thaw_canonical_json(self.metadata)
        if metadata:
            child_metadata.update(dict(metadata))
        return TraceContext(
            execution_identity=self.execution_identity,
            trace_id=self.trace_id,
            span_id=span_id if span_id is not None else new_span_id(),
            parent_span_id=self.span_id,
            agent_id=agent_id if agent_id is not None else self.agent_id,
            tool_call_id=(
                tool_call_id if tool_call_id is not None else self.tool_call_id
            ),
            memory_operation_id=(
                memory_operation_id
                if memory_operation_id is not None
                else self.memory_operation_id
            ),
            artifact_id=artifact_id if artifact_id is not None else self.artifact_id,
            metadata=child_metadata,
            trace_flags=self.trace_flags,
            tracestate=self.tracestate,
            is_remote=False,
        )

    def to_dict(
        self,
        *,
        redact: bool = True,
        redaction_policy: TraceRedactionPolicy | None = None,
    ) -> dict[str, Any]:
        metadata = thaw_canonical_json(self.metadata)
        if redact:
            metadata = redact_trace_payload(
                metadata,
                policy=redaction_policy or DEFAULT_TRACE_REDACTION_POLICY,
            )
        return {
            "schema_version": self.schema_version,
            "execution_identity": self.execution_identity.to_dict(),
            "trace_id": self.trace_id,
            "span_id": self.span_id,
            "parent_span_id": self.parent_span_id,
            "trace_flags": self.trace_flags,
            "tracestate": self.tracestate,
            "is_remote": self.is_remote,
            "agent_id": self.agent_id,
            "tool_call_id": self.tool_call_id,
            "memory_operation_id": self.memory_operation_id,
            "artifact_id": self.artifact_id,
            "metadata": metadata,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "TraceContext":
        if not isinstance(payload, Mapping) or set(payload) != _TRACE_CONTEXT_FIELDS:
            raise ValueError("trace context fields are invalid")
        metadata = payload.get("metadata") or {}
        if not isinstance(metadata, Mapping):
            raise TypeError("trace metadata must be an object")
        execution_identity = payload.get("execution_identity")
        if not isinstance(execution_identity, Mapping):
            raise TypeError("trace execution_identity must be an object")
        return cls(
            execution_identity=GraphExecutionIdentity.from_dict(execution_identity),
            trace_id=payload.get("trace_id"),
            span_id=payload.get("span_id"),
            parent_span_id=payload.get("parent_span_id"),
            agent_id=payload.get("agent_id"),
            tool_call_id=payload.get("tool_call_id"),
            memory_operation_id=payload.get("memory_operation_id"),
            artifact_id=payload.get("artifact_id"),
            metadata=metadata,
            trace_flags=payload.get("trace_flags", "00"),
            tracestate=payload.get("tracestate"),
            is_remote=payload.get("is_remote", False),
            schema_version=payload.get("schema_version"),
        )


@dataclass(frozen=True, slots=True)
class TraceEvent:
    event_type: str
    context: TraceContext
    component: str
    operation: str
    status: str
    event_id: str = field(default_factory=lambda: uuid4().hex)
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))
    duration_ms: float | None = None
    payload: Mapping[str, CanonicalValue] = field(default_factory=dict)
    error: Mapping[str, CanonicalValue] | None = None
    schema_version: str = TRACE_EVENT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        for field_name in (
            "event_type",
            "component",
            "operation",
            "status",
            "event_id",
            "schema_version",
        ):
            object.__setattr__(
                self,
                field_name,
                _required_str(getattr(self, field_name), field_name),
            )
        if not isinstance(self.context, TraceContext):
            raise TypeError("context must be TraceContext")
        object.__setattr__(self, "timestamp", ensure_utc(self.timestamp))
        object.__setattr__(self, "payload", _immutable_mapping(self.payload, "payload"))
        if self.error is not None:
            object.__setattr__(self, "error", _immutable_mapping(self.error, "error"))

    def to_dict(
        self,
        *,
        redact: bool = True,
        redaction_policy: TraceRedactionPolicy | None = None,
    ) -> dict[str, Any]:
        policy = redaction_policy or DEFAULT_TRACE_REDACTION_POLICY
        payload = thaw_canonical_json(self.payload)
        error = thaw_canonical_json(self.error) if self.error is not None else None
        if redact:
            payload = redact_trace_payload(payload, policy=policy)
            error = redact_trace_payload(error, policy=policy) if error is not None else None
        return {
            "schema_version": self.schema_version,
            "event_id": self.event_id,
            "event_type": self.event_type,
            "timestamp": format_datetime(self.timestamp),
            "context": self.context.to_dict(
                redact=redact,
                redaction_policy=policy,
            ),
            "component": self.component,
            "operation": self.operation,
            "status": self.status,
            "duration_ms": self.duration_ms,
            "payload": payload,
            "error": error,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "TraceEvent":
        timestamp = parse_datetime(payload.get("timestamp"))
        if timestamp is None:
            raise EventTimeError("trace event timestamp is required")
        context = payload.get("context")
        if not isinstance(context, Mapping):
            raise TypeError("trace event context must be an object")
        event_payload = payload.get("payload") or {}
        if not isinstance(event_payload, Mapping):
            raise TypeError("trace event payload must be an object")
        error = payload.get("error")
        if error is not None and not isinstance(error, Mapping):
            raise TypeError("trace event error must be an object")
        return cls(
            schema_version=payload.get("schema_version") or TRACE_EVENT_SCHEMA_VERSION,
            event_id=payload.get("event_id") or uuid4().hex,
            event_type=payload.get("event_type"),
            timestamp=timestamp,
            context=TraceContext.from_dict(context),
            component=payload.get("component"),
            operation=payload.get("operation"),
            status=payload.get("status"),
            duration_ms=(
                float(payload["duration_ms"])
                if payload.get("duration_ms") is not None
                else None
            ),
            payload=event_payload,
            error=error,
        )


def trace_fields(context: TraceContext | None) -> dict[str, Any]:
    if context is None:
        return {}
    identity = context.execution_identity
    return {
        **identity.to_dict(),
        "trace_id": context.trace_id,
        "span_id": context.span_id,
        "parent_span_id": context.parent_span_id,
        "trace_flags": context.trace_flags,
        "tracestate": context.tracestate,
        "is_remote": context.is_remote,
        "agent_id": context.agent_id,
        "tool_call_id": context.tool_call_id,
        "memory_operation_id": context.memory_operation_id,
        "artifact_id": context.artifact_id,
    }


def redact_trace_payload(
    value: Any,
    *,
    policy: TraceRedactionPolicy | None = None,
) -> Any:
    """Return a detached schema-aware projection without substring matching."""

    actual_policy = policy or DEFAULT_TRACE_REDACTION_POLICY
    if not isinstance(actual_policy, TraceRedactionPolicy):
        raise TypeError("policy must be TraceRedactionPolicy")
    return _redact_trace_value(value, policy=actual_policy, path="")


def is_valid_trace_id(value: Any) -> bool:
    return (
        isinstance(value, str)
        and _TRACE_ID_PATTERN.fullmatch(value) is not None
        and value != "0" * 32
    )


def is_valid_span_id(value: Any) -> bool:
    return (
        isinstance(value, str)
        and _SPAN_ID_PATTERN.fullmatch(value) is not None
        and value != "0" * 16
    )


def is_valid_trace_flags(value: Any) -> bool:
    return isinstance(value, str) and _TRACE_FLAGS_PATTERN.fullmatch(value) is not None


def new_trace_id() -> str:
    return _new_nonzero_hex(16)


def new_span_id() -> str:
    return _new_nonzero_hex(8)


def _new_nonzero_hex(size_bytes: int) -> str:
    while True:
        value = secrets.token_hex(size_bytes)
        if int(value, 16) != 0:
            return value


def _redact_trace_value(
    value: Any,
    *,
    policy: TraceRedactionPolicy,
    path: str,
) -> Any:
    if isinstance(value, Mapping):
        redacted: dict[str, Any] = {}
        for key, item in value.items():
            key_text = str(key)
            item_path = f"{path}/{_escape_pointer_token(key_text)}"
            if policy.is_sensitive(key=key_text, path=item_path):
                redacted[key_text] = REDACTED_TRACE_VALUE
            else:
                redacted[key_text] = _redact_trace_value(
                    item,
                    policy=policy,
                    path=item_path,
                )
        return redacted
    if isinstance(value, (list, tuple)):
        return [
            _redact_trace_value(item, policy=policy, path=f"{path}/{index}")
            for index, item in enumerate(value)
        ]
    return value


def _immutable_mapping(value: Any, field_name: str) -> Mapping[str, CanonicalValue]:
    if value is None:
        value = {}
    if not isinstance(value, Mapping):
        raise TypeError(f"trace {field_name} must be an object")
    normalized = normalize_canonical_json(value, path=f"$.{field_name}")
    if not isinstance(normalized, Mapping):  # pragma: no cover - guarded above
        raise EventCanonicalizationError(f"trace {field_name} must be an object")
    return normalized


def _required_str(value: Any, field_name: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be a string")
    if not value:
        raise ValueError(f"{field_name} is required")
    return value


def _optional_str(value: Any, field_name: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be a string")
    return value or None


def _normalize_credential_key(key: Any) -> str:
    if not isinstance(key, str):
        raise TypeError("trace redaction credential keys must be strings")
    separated = _CAMEL_BOUNDARY_1.sub(r"\1_\2", key.strip())
    separated = _CAMEL_BOUNDARY_2.sub(r"\1_\2", separated)
    return _KEY_SEPARATOR.sub("_", separated).strip("_").casefold()


def _normalize_policy_paths(values: Any, field_name: str) -> frozenset[str]:
    if isinstance(values, str):
        raise TypeError(f"trace redaction {field_name} must be a collection")
    normalized: set[str] = set()
    for value in values:
        if not isinstance(value, str):
            raise TypeError(f"trace redaction {field_name} entries must be strings")
        if not value.startswith("/") or "\r" in value or "\n" in value:
            raise ValueError(f"trace redaction {field_name} entries must be JSON pointers")
        normalized.add(value)
    return frozenset(normalized)


def _escape_pointer_token(value: str) -> str:
    return value.replace("~", "~0").replace("/", "~1")


DEFAULT_TRACE_REDACTION_POLICY = TraceRedactionPolicy()


__all__ = [
    "DEFAULT_TRACE_REDACTION_POLICY",
    "MAX_TRACESTATE_BYTES",
    "REDACTED_TRACE_VALUE",
    "TRACE_EVENT_SCHEMA_VERSION",
    "TRACE_CONTEXT_SCHEMA_VERSION",
    "TRACE_METADATA_SCHEMA_VERSION",
    "TraceContext",
    "TraceEvent",
    "TraceRedactionPolicy",
    "is_valid_span_id",
    "is_valid_trace_flags",
    "is_valid_trace_id",
    "new_span_id",
    "new_trace_id",
    "redact_trace_payload",
    "trace_fields",
]
