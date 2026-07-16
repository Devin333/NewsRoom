from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
from enum import Enum
import re
from types import MappingProxyType
from typing import Any, Protocol

from framework.events.trace import (
    MAX_TRACESTATE_BYTES,
    TraceContext,
    is_valid_span_id,
    is_valid_trace_id,
)


TRACEPARENT_HEADER = "traceparent"
TRACESTATE_HEADER = "tracestate"
BAGGAGE_HEADER = "baggage"

_TRACEPARENT_PATTERN = re.compile(
    r"00-([0-9a-f]{32})-([0-9a-f]{16})-([0-9a-f]{2})\Z"
)
_TRACESTATE_KEY_PATTERN = re.compile(
    r"(?:[a-z0-9][_0-9a-z\-*/]{0,240}@)?[a-z][_0-9a-z\-*/]{0,13}\Z"
)
_TRACESTATE_VALUE_PATTERN = re.compile(r"[\x20-\x2b\x2d-\x3c\x3e-\x7e]{1,256}\Z")
_BAGGAGE_KEY_PATTERN = re.compile(r"[!#$%&'*+.^_`|~0-9A-Za-z-]{1,256}\Z")
_BAGGAGE_VALUE_PATTERN = re.compile(r"[\x21-\x2b\x2d-\x3a\x3c-\x7e]{0,1024}\Z")


class TraceParentFailureAction(str, Enum):
    RESTART = "restart"
    REJECT = "reject"


class AuxiliaryFailureAction(str, Enum):
    DROP = "drop"
    REJECT = "reject"


class TracePropagationError(ValueError):
    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(f"trace propagation rejected: {reason}")


@dataclass(frozen=True, slots=True)
class TracePropagationPolicy:
    """Trust and resource limits shared by transport-specific adapters."""

    accept_remote_context: bool = True
    invalid_traceparent_action: TraceParentFailureAction = (
        TraceParentFailureAction.RESTART
    )
    untrusted_context_action: TraceParentFailureAction = TraceParentFailureAction.RESTART
    invalid_auxiliary_action: AuxiliaryFailureAction = AuxiliaryFailureAction.DROP
    tracestate_allowlist: frozenset[str] = frozenset()
    baggage_allowlist: frozenset[str] = frozenset()
    max_carrier_items: int = 64
    max_traceparent_bytes: int = 256
    max_tracestate_bytes: int = MAX_TRACESTATE_BYTES
    max_tracestate_members: int = 32
    max_baggage_bytes: int = 8192
    max_baggage_members: int = 64
    max_baggage_value_bytes: int = 1024

    def __post_init__(self) -> None:
        if not isinstance(self.accept_remote_context, bool):
            raise TypeError("accept_remote_context must be a boolean")
        object.__setattr__(
            self,
            "invalid_traceparent_action",
            TraceParentFailureAction(self.invalid_traceparent_action),
        )
        object.__setattr__(
            self,
            "untrusted_context_action",
            TraceParentFailureAction(self.untrusted_context_action),
        )
        object.__setattr__(
            self,
            "invalid_auxiliary_action",
            AuxiliaryFailureAction(self.invalid_auxiliary_action),
        )
        object.__setattr__(
            self,
            "tracestate_allowlist",
            frozenset(_validated_tracestate_key(key) for key in self.tracestate_allowlist),
        )
        object.__setattr__(
            self,
            "baggage_allowlist",
            frozenset(_validated_baggage_key(key) for key in self.baggage_allowlist),
        )
        for field_name in (
            "max_carrier_items",
            "max_traceparent_bytes",
            "max_tracestate_bytes",
            "max_tracestate_members",
            "max_baggage_bytes",
            "max_baggage_members",
            "max_baggage_value_bytes",
        ):
            value = getattr(self, field_name)
            if isinstance(value, bool) or not isinstance(value, int):
                raise TypeError(f"{field_name} must be an integer")
            if value <= 0:
                raise ValueError(f"{field_name} must be positive")


@dataclass(frozen=True, slots=True)
class ExtractedTraceContext:
    context: TraceContext
    baggage: Mapping[str, str] = MappingProxyType({})
    accepted_remote: bool = False
    restarted: bool = False
    diagnostics: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.context, TraceContext):
            raise TypeError("context must be TraceContext")
        baggage: dict[str, str] = {}
        for key, value in self.baggage.items():
            if not isinstance(key, str) or not isinstance(value, str):
                raise TypeError("extracted baggage keys and values must be strings")
            baggage[key] = value
        object.__setattr__(self, "baggage", MappingProxyType(baggage))
        if not isinstance(self.accepted_remote, bool) or not isinstance(
            self.restarted,
            bool,
        ):
            raise TypeError("trace extraction state must be boolean")
        diagnostics = tuple(str(item) for item in self.diagnostics)
        if len(diagnostics) > 8:
            raise ValueError("trace extraction diagnostics must be bounded")
        object.__setattr__(self, "diagnostics", diagnostics)

    def child(self, **fields: Any) -> "ExtractedTraceContext":
        return replace(self, context=self.context.child(**fields))


class W3CTracePropagator:
    """Pure W3C propagation core; transport adapters own carrier access."""

    def __init__(self, policy: TracePropagationPolicy | None = None) -> None:
        self._policy = policy or DEFAULT_TRACE_PROPAGATION_POLICY
        if not isinstance(self._policy, TracePropagationPolicy):
            raise TypeError("policy must be TracePropagationPolicy")

    @property
    def policy(self) -> TracePropagationPolicy:
        return self._policy

    def extract(
        self,
        carrier: Mapping[str, Any],
        *,
        run_id: str,
        workflow_id: str | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> ExtractedTraceContext:
        headers = _read_bounded_headers(carrier, self._policy)
        traceparent = headers.get(TRACEPARENT_HEADER)
        if traceparent is None:
            baggage, baggage_diagnostics = _parse_baggage(
                headers.get(BAGGAGE_HEADER),
                self._policy,
            )
            diagnostics = baggage_diagnostics
            if TRACESTATE_HEADER in headers:
                diagnostics = (*diagnostics, "orphan_tracestate_dropped")
            return ExtractedTraceContext(
                context=TraceContext.root(
                    run_id=run_id,
                    workflow_id=workflow_id,
                    metadata=metadata,
                ),
                baggage=baggage,
                diagnostics=diagnostics,
            )

        parsed = _parse_traceparent(traceparent, self._policy)
        if parsed is None:
            return self._restart_or_reject(
                action=self._policy.invalid_traceparent_action,
                reason="invalid_traceparent",
                run_id=run_id,
                workflow_id=workflow_id,
                metadata=metadata,
            )
        if not self._policy.accept_remote_context:
            return self._restart_or_reject(
                action=self._policy.untrusted_context_action,
                reason="untrusted_remote_context",
                run_id=run_id,
                workflow_id=workflow_id,
                metadata=metadata,
            )

        trace_id, span_id, trace_flags = parsed
        tracestate, tracestate_diagnostics = _parse_tracestate(
            headers.get(TRACESTATE_HEADER),
            self._policy,
        )
        baggage, baggage_diagnostics = _parse_baggage(
            headers.get(BAGGAGE_HEADER),
            self._policy,
        )
        return ExtractedTraceContext(
            context=TraceContext.root(
                run_id=run_id,
                workflow_id=workflow_id,
                trace_id=trace_id,
                span_id=span_id,
                metadata=metadata,
                trace_flags=trace_flags,
                tracestate=tracestate,
                is_remote=True,
            ),
            baggage=baggage,
            accepted_remote=True,
            diagnostics=(*tracestate_diagnostics, *baggage_diagnostics),
        )

    def inject(
        self,
        context: TraceContext,
        carrier: Mapping[str, Any] | None = None,
        *,
        baggage: Mapping[str, str] | None = None,
    ) -> dict[str, str]:
        if not isinstance(context, TraceContext):
            raise TypeError("context must be TraceContext")
        outbound = _copy_without_propagation_headers(carrier or {}, self._policy)
        if not context.is_injectable:
            return outbound

        outbound[TRACEPARENT_HEADER] = (
            f"00-{context.trace_id}-{context.span_id}-{context.trace_flags}"
        )
        tracestate, _ = _parse_tracestate(context.tracestate, self._policy)
        if tracestate is not None:
            outbound[TRACESTATE_HEADER] = tracestate
        baggage_header = _format_baggage(baggage or {}, self._policy)
        if baggage_header is not None:
            outbound[BAGGAGE_HEADER] = baggage_header
        if len(outbound) > self._policy.max_carrier_items:
            raise TracePropagationError("carrier_item_limit")
        return outbound

    @staticmethod
    def _restart_or_reject(
        *,
        action: TraceParentFailureAction,
        reason: str,
        run_id: str,
        workflow_id: str | None,
        metadata: Mapping[str, Any] | None,
    ) -> ExtractedTraceContext:
        if action is TraceParentFailureAction.REJECT:
            raise TracePropagationError(reason)
        return ExtractedTraceContext(
            context=TraceContext.root(
                run_id=run_id,
                workflow_id=workflow_id,
                metadata=metadata,
            ),
            restarted=True,
            diagnostics=(reason,),
        )


class TraceAdapter(Protocol):
    available: bool

    def root(self, **fields: Any) -> TraceContext: ...

    def child(self, context: TraceContext, **fields: Any) -> TraceContext: ...

    def to_native_context(self, context: TraceContext) -> Any | None: ...


@dataclass(frozen=True, slots=True)
class NoOpTraceAdapter:
    """Fallback that preserves facade behavior without telemetry dependencies."""

    available: bool = False

    def root(self, **fields: Any) -> TraceContext:
        return TraceContext.root(**fields)

    def child(self, context: TraceContext, **fields: Any) -> TraceContext:
        return context.child(**fields)

    def to_native_context(self, context: TraceContext) -> None:
        if not isinstance(context, TraceContext):
            raise TypeError("context must be TraceContext")
        return None


class OpenTelemetryTraceAdapter:
    """Lazy conversion boundary for the optional OpenTelemetry API."""

    available = True

    def __init__(self) -> None:
        span_context, trace_flags, trace_state = _load_otel_bindings()
        self._span_context_type = span_context
        self._trace_flags_type = trace_flags
        self._trace_state_type = trace_state

    def root(self, **fields: Any) -> TraceContext:
        return TraceContext.root(**fields)

    def child(self, context: TraceContext, **fields: Any) -> TraceContext:
        return context.child(**fields)

    def to_native_context(self, context: TraceContext) -> Any | None:
        if not isinstance(context, TraceContext):
            raise TypeError("context must be TraceContext")
        if not context.is_injectable:
            return None
        trace_state = self._trace_state_type()
        if context.tracestate:
            try:
                trace_state = self._trace_state_type.from_header([context.tracestate])
            except Exception:
                trace_state = self._trace_state_type()
        return self._span_context_type(
            trace_id=int(context.trace_id, 16),
            span_id=int(context.span_id, 16),
            is_remote=context.is_remote,
            trace_flags=self._trace_flags_type(int(context.trace_flags, 16)),
            trace_state=trace_state,
        )

    def from_native_context(
        self,
        native_context: Any,
        *,
        run_id: str,
        workflow_id: str | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> TraceContext | None:
        if native_context is None or not bool(getattr(native_context, "is_valid", False)):
            return None
        trace_id = int(getattr(native_context, "trace_id", 0))
        span_id = int(getattr(native_context, "span_id", 0))
        if trace_id <= 0 or span_id <= 0:
            return None
        native_state = getattr(native_context, "trace_state", None)
        tracestate = None
        if native_state is not None and hasattr(native_state, "to_header"):
            tracestate = str(native_state.to_header() or "") or None
        return TraceContext.root(
            run_id=run_id,
            workflow_id=workflow_id,
            trace_id=f"{trace_id:032x}",
            span_id=f"{span_id:016x}",
            metadata=metadata,
            trace_flags=f"{int(getattr(native_context, 'trace_flags', 0)):02x}",
            tracestate=tracestate,
            is_remote=bool(getattr(native_context, "is_remote", False)),
        )


def default_trace_adapter() -> TraceAdapter:
    try:
        return OpenTelemetryTraceAdapter()
    except Exception:
        return NoOpTraceAdapter()


def _read_bounded_headers(
    carrier: Mapping[str, Any],
    policy: TracePropagationPolicy,
) -> dict[str, str]:
    if not isinstance(carrier, Mapping):
        raise TypeError("trace carrier must be a mapping")
    if len(carrier) > policy.max_carrier_items:
        raise TracePropagationError("carrier_item_limit")
    headers: dict[str, str] = {}
    for key, value in carrier.items():
        if not isinstance(key, str):
            continue
        normalized = key.casefold()
        if normalized not in {
            TRACEPARENT_HEADER,
            TRACESTATE_HEADER,
            BAGGAGE_HEADER,
        }:
            continue
        if normalized in headers:
            raise TracePropagationError(f"duplicate_{normalized}")
        if not isinstance(value, str):
            raise TracePropagationError(f"non_string_{normalized}")
        if "\r" in value or "\n" in value:
            raise TracePropagationError(f"line_break_{normalized}")
        headers[normalized] = value.strip()
    return headers


def _copy_without_propagation_headers(
    carrier: Mapping[str, Any],
    policy: TracePropagationPolicy,
) -> dict[str, str]:
    if not isinstance(carrier, Mapping):
        raise TypeError("trace carrier must be a mapping")
    if len(carrier) > policy.max_carrier_items:
        raise TracePropagationError("carrier_item_limit")
    outbound: dict[str, str] = {}
    for key, value in carrier.items():
        if not isinstance(key, str) or not isinstance(value, str):
            raise TypeError("outbound carrier keys and values must be strings")
        if key.casefold() in {TRACEPARENT_HEADER, TRACESTATE_HEADER, BAGGAGE_HEADER}:
            continue
        outbound[key] = value
    return outbound


def _parse_traceparent(
    value: str,
    policy: TracePropagationPolicy,
) -> tuple[str, str, str] | None:
    if len(value.encode("utf-8")) > policy.max_traceparent_bytes:
        return None
    match = _TRACEPARENT_PATTERN.fullmatch(value)
    if match is None:
        return None
    trace_id, span_id, trace_flags = match.groups()
    if not is_valid_trace_id(trace_id) or not is_valid_span_id(span_id):
        return None
    return trace_id, span_id, trace_flags


def _parse_tracestate(
    value: str | None,
    policy: TracePropagationPolicy,
) -> tuple[str | None, tuple[str, ...]]:
    if value is None or not value:
        return None, ()
    if len(value.encode("utf-8")) > policy.max_tracestate_bytes:
        return _auxiliary_failure(policy, "tracestate_size_limit", None)
    members = [member.strip() for member in value.split(",")]
    if not members or len(members) > policy.max_tracestate_members:
        return _auxiliary_failure(policy, "tracestate_member_limit", None)
    accepted: list[str] = []
    seen: set[str] = set()
    dropped = False
    for member in members:
        if "=" not in member:
            return _auxiliary_failure(policy, "invalid_tracestate", None)
        key, item_value = member.split("=", 1)
        if (
            _TRACESTATE_KEY_PATTERN.fullmatch(key) is None
            or _TRACESTATE_VALUE_PATTERN.fullmatch(item_value) is None
            or item_value.endswith(" ")
            or key in seen
        ):
            return _auxiliary_failure(policy, "invalid_tracestate", None)
        seen.add(key)
        if key in policy.tracestate_allowlist:
            accepted.append(f"{key}={item_value}")
        else:
            dropped = True
    diagnostics = ("tracestate_disallowed_members_dropped",) if dropped else ()
    return (",".join(accepted) or None), diagnostics


def _parse_baggage(
    value: str | None,
    policy: TracePropagationPolicy,
) -> tuple[Mapping[str, str], tuple[str, ...]]:
    if value is None or not value:
        return MappingProxyType({}), ()
    if len(value.encode("utf-8")) > policy.max_baggage_bytes:
        empty, diagnostics = _auxiliary_failure(policy, "baggage_size_limit", {})
        return MappingProxyType(empty), diagnostics
    members = [member.strip() for member in value.split(",")]
    if not members or len(members) > policy.max_baggage_members:
        empty, diagnostics = _auxiliary_failure(policy, "baggage_member_limit", {})
        return MappingProxyType(empty), diagnostics
    accepted: dict[str, str] = {}
    seen: set[str] = set()
    dropped = False
    for member in members:
        pair = member.split(";", 1)[0].strip()
        if "=" not in pair:
            empty, diagnostics = _auxiliary_failure(policy, "invalid_baggage", {})
            return MappingProxyType(empty), diagnostics
        key, item_value = pair.split("=", 1)
        try:
            normalized_key = _validated_baggage_key(key)
        except (TypeError, ValueError):
            empty, diagnostics = _auxiliary_failure(policy, "invalid_baggage", {})
            return MappingProxyType(empty), diagnostics
        if (
            normalized_key in seen
            or _BAGGAGE_VALUE_PATTERN.fullmatch(item_value) is None
            or len(item_value.encode("utf-8")) > policy.max_baggage_value_bytes
        ):
            empty, diagnostics = _auxiliary_failure(policy, "invalid_baggage", {})
            return MappingProxyType(empty), diagnostics
        seen.add(normalized_key)
        if normalized_key in policy.baggage_allowlist:
            accepted[normalized_key] = item_value
        else:
            dropped = True
    diagnostics = ("baggage_disallowed_members_dropped",) if dropped else ()
    return MappingProxyType(accepted), diagnostics


def _format_baggage(
    baggage: Mapping[str, str],
    policy: TracePropagationPolicy,
) -> str | None:
    if not isinstance(baggage, Mapping):
        raise TypeError("baggage must be a mapping")
    if len(baggage) > policy.max_baggage_members:
        if policy.invalid_auxiliary_action is AuxiliaryFailureAction.REJECT:
            raise TracePropagationError("baggage_member_limit")
        return None
    members: list[str] = []
    for key, value in baggage.items():
        try:
            normalized_key = _validated_baggage_key(key)
        except (TypeError, ValueError):
            if policy.invalid_auxiliary_action is AuxiliaryFailureAction.REJECT:
                raise TracePropagationError("invalid_baggage") from None
            return None
        if normalized_key not in policy.baggage_allowlist:
            continue
        if not isinstance(value, str) or _BAGGAGE_VALUE_PATTERN.fullmatch(value) is None:
            if policy.invalid_auxiliary_action is AuxiliaryFailureAction.REJECT:
                raise TracePropagationError("invalid_baggage")
            return None
        if len(value.encode("utf-8")) > policy.max_baggage_value_bytes:
            if policy.invalid_auxiliary_action is AuxiliaryFailureAction.REJECT:
                raise TracePropagationError("baggage_value_limit")
            return None
        members.append(f"{normalized_key}={value}")
    header = ",".join(members)
    if header and len(header.encode("utf-8")) > policy.max_baggage_bytes:
        if policy.invalid_auxiliary_action is AuxiliaryFailureAction.REJECT:
            raise TracePropagationError("baggage_size_limit")
        return None
    return header or None


def _auxiliary_failure(
    policy: TracePropagationPolicy,
    reason: str,
    empty: Any,
) -> tuple[Any, tuple[str, ...]]:
    if policy.invalid_auxiliary_action is AuxiliaryFailureAction.REJECT:
        raise TracePropagationError(reason)
    return empty, (reason,)


def _validated_tracestate_key(value: Any) -> str:
    if not isinstance(value, str):
        raise TypeError("tracestate allowlist keys must be strings")
    if _TRACESTATE_KEY_PATTERN.fullmatch(value) is None:
        raise ValueError("invalid tracestate allowlist key")
    return value


def _validated_baggage_key(value: Any) -> str:
    if not isinstance(value, str):
        raise TypeError("baggage keys must be strings")
    normalized = value.casefold()
    if _BAGGAGE_KEY_PATTERN.fullmatch(normalized) is None:
        raise ValueError("invalid baggage key")
    return normalized


def _load_otel_bindings() -> tuple[Any, Any, Any]:
    from opentelemetry.trace import SpanContext, TraceFlags, TraceState

    return SpanContext, TraceFlags, TraceState


DEFAULT_TRACE_PROPAGATION_POLICY = TracePropagationPolicy()


__all__ = [
    "AuxiliaryFailureAction",
    "BAGGAGE_HEADER",
    "DEFAULT_TRACE_PROPAGATION_POLICY",
    "ExtractedTraceContext",
    "NoOpTraceAdapter",
    "OpenTelemetryTraceAdapter",
    "TRACEPARENT_HEADER",
    "TRACESTATE_HEADER",
    "TraceAdapter",
    "TraceParentFailureAction",
    "TracePropagationError",
    "TracePropagationPolicy",
    "W3CTracePropagator",
    "default_trace_adapter",
]
