from __future__ import annotations

from collections.abc import Mapping
from contextlib import contextmanager
from contextvars import ContextVar, Token
from dataclasses import dataclass, field, replace
from enum import Enum
import re
from types import MappingProxyType
from typing import Any, Iterator, Protocol

from framework.events.trace import (
    MAX_TRACESTATE_BYTES,
    TraceContext,
    is_valid_span_id,
    is_valid_trace_flags,
    is_valid_trace_id,
    new_span_id,
    new_trace_id,
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
_CURRENT_TRACE_CONTEXT: ContextVar[TraceContext | W3CSpanContext | None]


@dataclass(frozen=True, slots=True)
class W3CSpanContext:
    """Transport span context with no business run or authorization identity."""

    trace_id: str
    span_id: str
    trace_flags: str = "00"
    tracestate: str | None = None
    is_remote: bool = False
    parent_span_id: str | None = None

    def __post_init__(self) -> None:
        if not is_valid_trace_id(self.trace_id):
            raise ValueError("trace_id must be a nonzero W3C trace id")
        if not is_valid_span_id(self.span_id):
            raise ValueError("span_id must be a nonzero W3C span id")
        if not is_valid_trace_flags(self.trace_flags):
            raise ValueError("trace_flags must be two lowercase hexadecimal characters")
        if self.parent_span_id is not None and not is_valid_span_id(self.parent_span_id):
            raise ValueError("parent_span_id must be a nonzero W3C span id")
        if not isinstance(self.is_remote, bool):
            raise TypeError("is_remote must be a boolean")
        if self.tracestate is not None:
            if not isinstance(self.tracestate, str):
                raise TypeError("tracestate must be a string")
            if "\r" in self.tracestate or "\n" in self.tracestate:
                raise ValueError("tracestate cannot contain line breaks")
            if len(self.tracestate.encode("utf-8")) > MAX_TRACESTATE_BYTES:
                raise ValueError("tracestate exceeds the W3C byte limit")

    @property
    def is_injectable(self) -> bool:
        return True

    @classmethod
    def root(cls) -> "W3CSpanContext":
        return cls(trace_id=new_trace_id(), span_id=new_span_id())

    @classmethod
    def from_trace_context(
        cls,
        context: TraceContext | None,
    ) -> "W3CSpanContext | None":
        if context is None or not context.is_injectable:
            return None
        return cls(
            trace_id=context.trace_id,
            span_id=context.span_id,
            trace_flags=context.trace_flags,
            tracestate=context.tracestate,
            is_remote=context.is_remote,
            parent_span_id=(
                context.parent_span_id
                if context.parent_span_id is None
                or is_valid_span_id(context.parent_span_id)
                else None
            ),
        )

    @classmethod
    def from_trace_block(cls, trace: Any) -> "W3CSpanContext | None":
        if trace is None:
            return None
        try:
            return cls(
                trace_id=trace.trace_id,
                span_id=trace.span_id,
                trace_flags=trace.trace_flags,
                tracestate=trace.tracestate,
                is_remote=trace.is_remote,
                parent_span_id=trace.parent_span_id,
            )
        except (AttributeError, TypeError, ValueError):
            return None

    def child(self) -> "W3CSpanContext":
        return W3CSpanContext(
            trace_id=self.trace_id,
            span_id=new_span_id(),
            parent_span_id=self.span_id,
            trace_flags=self.trace_flags,
            tracestate=self.tracestate,
            is_remote=False,
        )

    def to_trace_context(
        self,
        *,
        run_id: str,
        workflow_id: str | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> TraceContext:
        return TraceContext.root(
            run_id=run_id,
            workflow_id=workflow_id,
            trace_id=self.trace_id,
            span_id=self.span_id,
            metadata=metadata,
            trace_flags=self.trace_flags,
            tracestate=self.tracestate,
            is_remote=self.is_remote,
        )


_CURRENT_TRACE_CONTEXT = ContextVar(
    "newsroom_current_trace_context",
    default=None,
)


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
class ExtractedSpanContext:
    context: W3CSpanContext
    remote_context: W3CSpanContext | None = None
    baggage: Mapping[str, str] = field(default_factory=dict)
    accepted_remote: bool = False
    restarted: bool = False
    diagnostics: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.context, W3CSpanContext):
            raise TypeError("context must be W3CSpanContext")
        if self.remote_context is not None and not isinstance(
            self.remote_context,
            W3CSpanContext,
        ):
            raise TypeError("remote_context must be W3CSpanContext")
        baggage = _immutable_baggage(self.baggage)
        object.__setattr__(self, "baggage", baggage)
        diagnostics = tuple(str(item) for item in self.diagnostics)
        if len(diagnostics) > 8:
            raise ValueError("trace extraction diagnostics must be bounded")
        object.__setattr__(self, "diagnostics", diagnostics)

    def child(self) -> "ExtractedSpanContext":
        return replace(self, context=self.context.child())


@dataclass(frozen=True, slots=True)
class ExtractedTraceContext:
    context: TraceContext
    remote_context: TraceContext | None = None
    baggage: Mapping[str, str] = field(default_factory=dict)
    accepted_remote: bool = False
    restarted: bool = False
    diagnostics: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.context, TraceContext):
            raise TypeError("context must be TraceContext")
        if self.remote_context is not None and not isinstance(
            self.remote_context,
            TraceContext,
        ):
            raise TypeError("remote_context must be TraceContext")
        object.__setattr__(self, "baggage", _immutable_baggage(self.baggage))
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
        extracted = self.extract_span(carrier)
        context = extracted.context.to_trace_context(
            run_id=run_id,
            workflow_id=workflow_id,
            metadata=metadata,
        )
        remote_context = (
            extracted.remote_context.to_trace_context(
                run_id=run_id,
                workflow_id=workflow_id,
                metadata=metadata,
            )
            if extracted.remote_context is not None
            else None
        )
        return ExtractedTraceContext(
            context=context,
            remote_context=remote_context,
            baggage=extracted.baggage,
            accepted_remote=extracted.accepted_remote,
            restarted=extracted.restarted,
            diagnostics=extracted.diagnostics,
        )

    def extract_span(self, carrier: Mapping[str, Any]) -> ExtractedSpanContext:
        """Extract transport context without inventing a business run identity."""

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
            return ExtractedSpanContext(
                context=W3CSpanContext.root(),
                baggage=baggage,
                diagnostics=diagnostics,
            )

        parsed = _parse_traceparent(traceparent, self._policy)
        if parsed is None:
            return self._restart_or_reject_span(
                action=self._policy.invalid_traceparent_action,
                reason="invalid_traceparent",
            )
        if not self._policy.accept_remote_context:
            return self._restart_or_reject_span(
                action=self._policy.untrusted_context_action,
                reason="untrusted_remote_context",
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
        remote_context = W3CSpanContext(
            trace_id=trace_id,
            span_id=span_id,
            trace_flags=trace_flags,
            tracestate=tracestate,
            is_remote=True,
        )
        return ExtractedSpanContext(
            context=remote_context,
            remote_context=remote_context,
            baggage=baggage,
            accepted_remote=True,
            diagnostics=(*tracestate_diagnostics, *baggage_diagnostics),
        )

    def inject(
        self,
        context: TraceContext | W3CSpanContext,
        carrier: Mapping[str, Any] | None = None,
        *,
        baggage: Mapping[str, str] | None = None,
    ) -> dict[str, str]:
        if not isinstance(context, (TraceContext, W3CSpanContext)):
            raise TypeError("context must be TraceContext or W3CSpanContext")
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
    def _restart_or_reject_span(
        *,
        action: TraceParentFailureAction,
        reason: str,
    ) -> ExtractedSpanContext:
        if action is TraceParentFailureAction.REJECT:
            raise TracePropagationError(reason)
        return ExtractedSpanContext(
            context=W3CSpanContext.root(),
            restarted=True,
            diagnostics=(reason,),
        )


class TraceAdapter(Protocol):
    available: bool

    def root(self, **fields: Any) -> TraceContext: ...

    def child(self, context: TraceContext, **fields: Any) -> TraceContext: ...

    def to_native_context(
        self,
        context: TraceContext | W3CSpanContext,
    ) -> Any | None: ...


@dataclass(frozen=True, slots=True)
class NoOpTraceAdapter:
    """Fallback that preserves facade behavior without telemetry dependencies."""

    available: bool = False

    def root(self, **fields: Any) -> TraceContext:
        return TraceContext.root(**fields)

    def child(self, context: TraceContext, **fields: Any) -> TraceContext:
        return context.child(**fields)

    def to_native_context(
        self,
        context: TraceContext | W3CSpanContext,
    ) -> None:
        if not isinstance(context, (TraceContext, W3CSpanContext)):
            raise TypeError("context must be TraceContext or W3CSpanContext")
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

    def to_native_context(
        self,
        context: TraceContext | W3CSpanContext,
    ) -> Any | None:
        if not isinstance(context, (TraceContext, W3CSpanContext)):
            raise TypeError("context must be TraceContext or W3CSpanContext")
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


def current_trace_context() -> TraceContext | W3CSpanContext | None:
    """Return the immutable trace context scoped to this async/thread context."""

    return _CURRENT_TRACE_CONTEXT.get()


def attach_trace_context(
    context: TraceContext | W3CSpanContext | None,
) -> Token[TraceContext | W3CSpanContext | None]:
    if context is not None and not isinstance(context, (TraceContext, W3CSpanContext)):
        raise TypeError("context must be TraceContext or W3CSpanContext")
    return _CURRENT_TRACE_CONTEXT.set(context)


def reset_trace_context(
    token: Token[TraceContext | W3CSpanContext | None],
) -> None:
    _CURRENT_TRACE_CONTEXT.reset(token)


@contextmanager
def trace_context_scope(
    context: TraceContext | W3CSpanContext | None,
) -> Iterator[TraceContext | W3CSpanContext | None]:
    token = attach_trace_context(context)
    try:
        yield context
    finally:
        reset_trace_context(token)


def inject_current_trace(
    carrier: Mapping[str, Any] | None = None,
    *,
    baggage: Mapping[str, str] | None = None,
    propagator: W3CTracePropagator | None = None,
) -> dict[str, str]:
    actual = propagator or W3CTracePropagator()
    context = current_trace_context()
    if context is None:
        return _copy_without_propagation_headers(carrier or {}, actual.policy)
    return actual.inject(context, carrier, baggage=baggage)


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


def _immutable_baggage(value: Mapping[str, str]) -> Mapping[str, str]:
    if not isinstance(value, Mapping):
        raise TypeError("baggage must be a mapping")
    baggage: dict[str, str] = {}
    for key, item in value.items():
        if not isinstance(key, str) or not isinstance(item, str):
            raise TypeError("baggage keys and values must be strings")
        baggage[key] = item
    return MappingProxyType(baggage)


def _load_otel_bindings() -> tuple[Any, Any, Any]:
    from opentelemetry.trace import SpanContext, TraceFlags, TraceState

    return SpanContext, TraceFlags, TraceState


DEFAULT_TRACE_PROPAGATION_POLICY = TracePropagationPolicy()


def normalize_trace_carrier(
    value: Mapping[str, Any] | None,
    *,
    policy: TracePropagationPolicy | None = None,
    immutable: bool = True,
) -> Mapping[str, str]:
    """Validate and snapshot the shared W3C transport carrier contract."""

    if value is None:
        carrier: dict[str, str] = {}
        return MappingProxyType(carrier) if immutable else carrier
    if not isinstance(value, Mapping):
        raise TypeError("trace_carrier must be a mapping")
    actual_policy = policy or DEFAULT_TRACE_PROPAGATION_POLICY
    if len(value) > actual_policy.max_carrier_items:
        raise ValueError("trace_carrier exceeds the item limit")
    byte_limits = {
        TRACEPARENT_HEADER: actual_policy.max_traceparent_bytes,
        TRACESTATE_HEADER: actual_policy.max_tracestate_bytes,
        BAGGAGE_HEADER: actual_policy.max_baggage_bytes,
    }
    carrier = {}
    for key, item in value.items():
        if not isinstance(key, str):
            raise TypeError("trace_carrier keys must be strings")
        normalized = key.casefold()
        if normalized not in byte_limits:
            raise ValueError("trace_carrier contains an unsupported header")
        if normalized in carrier:
            raise ValueError("trace_carrier contains a duplicate header")
        if not isinstance(item, str):
            raise TypeError("trace_carrier values must be strings")
        if "\r" in item or "\n" in item:
            raise ValueError("trace_carrier values cannot contain line breaks")
        if len(item.encode("utf-8")) > byte_limits[normalized]:
            raise ValueError(f"trace_carrier {normalized} exceeds the byte limit")
        carrier[normalized] = item
    return MappingProxyType(carrier) if immutable else carrier


__all__ = [
    "AuxiliaryFailureAction",
    "BAGGAGE_HEADER",
    "DEFAULT_TRACE_PROPAGATION_POLICY",
    "ExtractedSpanContext",
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
    "W3CSpanContext",
    "attach_trace_context",
    "current_trace_context",
    "default_trace_adapter",
    "inject_current_trace",
    "normalize_trace_carrier",
    "reset_trace_context",
    "trace_context_scope",
]
