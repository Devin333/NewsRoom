from __future__ import annotations

from collections.abc import Callable, Mapping
from contextlib import AbstractContextManager
from dataclasses import dataclass, field
import re
from types import MappingProxyType
from typing import Any, Protocol

from framework.events.propagation import OpenTelemetryTraceAdapter, W3CSpanContext
from framework.events.trace import TraceContext


MAX_TELEMETRY_ATTRIBUTES = 24
MAX_TELEMETRY_ATTRIBUTE_LENGTH = 96
MAX_TELEMETRY_LINKS = 32

_IDENTITY_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:/-]{0,95}\Z")
_SPAN_ATTRIBUTES = frozenset(
    {
        "newsroom.batch.size",
        "newsroom.component",
        "newsroom.delivery.attempt_bucket",
        "newsroom.delivery.consumer",
        "newsroom.delivery.generation_bucket",
        "newsroom.error.type",
        "newsroom.event.type",
        "newsroom.operation",
        "newsroom.outcome",
        "newsroom.propagation.result",
        "newsroom.retry.scheduled",
        "newsroom.status",
        "newsroom.tool.name",
        "newsroom.transport",
        "newsroom.worker.attempt_bucket",
        "newsroom.worker.queue",
        "newsroom.worker.task_type",
    }
)
_LINK_ATTRIBUTES = frozenset(
    {
        "newsroom.link.relationship",
        "newsroom.link.attempt_bucket",
    }
)
_METRIC_LABELS: Mapping[str, frozenset[str]] = MappingProxyType(
    {
        "event_append_total": frozenset({"backend", "result"}),
        "event_delivery_attempt_total": frozenset({"consumer", "outcome"}),
        "event_dead_letter_total": frozenset({"consumer", "reason_class"}),
        "event_quarantine_total": frozenset({"reason"}),
        "event_replay_total": frozenset({"mode", "result"}),
        "event_schema_validation_total": frozenset({"event_type", "result"}),
        "trace_propagation_total": frozenset({"boundary", "result"}),
    }
)
_METRIC_LABEL_VALUE_DOMAINS: Mapping[str, frozenset[str]] = MappingProxyType(
    {
        "backend": frozenset({"sqlite", "postgresql", "memory", "unknown"}),
        "boundary": frozenset(
            {
                "event_delivery",
                "http",
                "mcp",
                "subagent",
                "tool_http",
                "tool_mcp",
                "worker",
            }
        ),
        "consumer": frozenset(
            {"audit", "harness", "projection", "telemetry", "unknown", "workflow"}
        ),
        "event_type": frozenset({"registered", "unknown"}),
        "mode": frozenset({"rebuild_state", "redeliver", "verify_history"}),
        "outcome": frozenset(
            {"ack", "dead_letter", "drop", "failed", "retry", "unknown"}
        ),
        "reason": frozenset(
            {"conflict", "integrity", "missing_time", "schema", "unknown"}
        ),
        "reason_class": frozenset(
            {"contract", "permanent", "retry_exhausted", "unknown"}
        ),
        "result": frozenset(
            {
                "accepted",
                "duplicate",
                "failed",
                "invalid",
                "restarted",
                "success",
                "unknown",
            }
        ),
    }
)


@dataclass(frozen=True, slots=True)
class TelemetryResource:
    """Service/process identity owned by composition, never event metadata."""

    service_name: str
    service_version: str | None = None
    service_instance_id: str | None = None
    deployment_environment: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "service_name", _identity(self.service_name, "service_name"))
        for field_name in (
            "service_version",
            "service_instance_id",
            "deployment_environment",
        ):
            value = getattr(self, field_name)
            object.__setattr__(
                self,
                field_name,
                _optional_identity(value, field_name),
            )

    def to_attributes(self) -> Mapping[str, str]:
        attributes = {"service.name": self.service_name}
        if self.service_version is not None:
            attributes["service.version"] = self.service_version
        if self.service_instance_id is not None:
            attributes["service.instance.id"] = self.service_instance_id
        if self.deployment_environment is not None:
            attributes["deployment.environment.name"] = self.deployment_environment
        return MappingProxyType(attributes)


@dataclass(frozen=True, slots=True)
class TelemetryInstrumentationScope:
    """Library/component identity mapped to OpenTelemetry InstrumentationScope."""

    name: str
    version: str | None = None
    schema_url: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "name", _identity(self.name, "scope name"))
        object.__setattr__(
            self,
            "version",
            _optional_identity(self.version, "scope version"),
        )
        schema_url = self.schema_url
        if schema_url is not None:
            if not isinstance(schema_url, str) or len(schema_url) > 256:
                raise ValueError("scope schema_url must be a bounded string")
            if "\r" in schema_url or "\n" in schema_url:
                raise ValueError("scope schema_url cannot contain line breaks")
        object.__setattr__(self, "schema_url", schema_url or None)


@dataclass(frozen=True, slots=True)
class TelemetryAttributePolicy:
    allowed_span_attributes: frozenset[str] = _SPAN_ATTRIBUTES
    allowed_link_attributes: frozenset[str] = _LINK_ATTRIBUTES
    max_attributes: int = MAX_TELEMETRY_ATTRIBUTES
    max_value_length: int = MAX_TELEMETRY_ATTRIBUTE_LENGTH

    def __post_init__(self) -> None:
        for field_name in ("max_attributes", "max_value_length"):
            value = getattr(self, field_name)
            if isinstance(value, bool) or not isinstance(value, int):
                raise TypeError(f"{field_name} must be an integer")
            if value <= 0:
                raise ValueError(f"{field_name} must be positive")
        object.__setattr__(
            self,
            "allowed_span_attributes",
            frozenset(str(key) for key in self.allowed_span_attributes),
        )
        object.__setattr__(
            self,
            "allowed_link_attributes",
            frozenset(str(key) for key in self.allowed_link_attributes),
        )

    def span_attributes(self, values: Mapping[str, Any] | None) -> Mapping[str, Any]:
        return self._project(values, self.allowed_span_attributes)

    def link_attributes(self, values: Mapping[str, Any] | None) -> Mapping[str, Any]:
        return self._project(values, self.allowed_link_attributes)

    def _project(
        self,
        values: Mapping[str, Any] | None,
        allowed: frozenset[str],
    ) -> Mapping[str, Any]:
        if values is None:
            return MappingProxyType({})
        if not isinstance(values, Mapping):
            return MappingProxyType({})
        projected: dict[str, Any] = {}
        for key, value in values.items():
            if key not in allowed or len(projected) >= self.max_attributes:
                continue
            safe = _attribute_value(value, max_length=self.max_value_length)
            if safe is not None:
                projected[str(key)] = safe
        return MappingProxyType(projected)


DEFAULT_TELEMETRY_ATTRIBUTE_POLICY = TelemetryAttributePolicy()


@dataclass(frozen=True, slots=True)
class TelemetrySpanLink:
    context: TraceContext | W3CSpanContext
    attributes: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.context, (TraceContext, W3CSpanContext)) or not (
            self.context.is_injectable
        ):
            raise ValueError("telemetry link requires an injectable W3C context")
        object.__setattr__(
            self,
            "attributes",
            DEFAULT_TELEMETRY_ATTRIBUTE_POLICY.link_attributes(self.attributes),
        )

    @classmethod
    def from_context(
        cls,
        context: TraceContext | W3CSpanContext | None,
        *,
        relationship: str,
        attempt_bucket: str | None = None,
    ) -> "TelemetrySpanLink | None":
        if context is None or not context.is_injectable:
            return None
        attributes: dict[str, Any] = {"newsroom.link.relationship": relationship}
        if attempt_bucket is not None:
            attributes["newsroom.link.attempt_bucket"] = attempt_bucket
        return cls(context=context, attributes=attributes)

    @classmethod
    def from_trace_block(
        cls,
        trace: Any,
        *,
        relationship: str,
        attempt_bucket: str | None = None,
    ) -> "TelemetrySpanLink | None":
        return cls.from_context(
            W3CSpanContext.from_trace_block(trace),
            relationship=relationship,
            attempt_bucket=attempt_bucket,
        )


class TelemetryBackend(Protocol):
    def start_span(
        self,
        name: str,
        *,
        attributes: Mapping[str, Any],
        links: tuple[TelemetrySpanLink, ...],
    ) -> AbstractContextManager[Any]: ...

    def add_counter(
        self,
        name: str,
        value: int,
        *,
        attributes: Mapping[str, Any],
    ) -> None: ...


class _NoOpNativeSpan:
    def set_attribute(self, _key: str, _value: Any) -> None:
        return None

    def add_event(
        self,
        _name: str,
        *,
        attributes: Mapping[str, Any] | None = None,
    ) -> None:
        return None


class _NoOpSpanScope(AbstractContextManager[_NoOpNativeSpan]):
    def __enter__(self) -> _NoOpNativeSpan:
        return _NoOpNativeSpan()

    def __exit__(self, exc_type: Any, exc: BaseException | None, traceback: Any) -> bool:
        return False


@dataclass(frozen=True, slots=True)
class NoOpTelemetryBackend:
    resource: TelemetryResource
    scope: TelemetryInstrumentationScope

    def start_span(
        self,
        name: str,
        *,
        attributes: Mapping[str, Any],
        links: tuple[TelemetrySpanLink, ...],
    ) -> AbstractContextManager[Any]:
        return _NoOpSpanScope()

    def add_counter(
        self,
        name: str,
        value: int,
        *,
        attributes: Mapping[str, Any],
    ) -> None:
        return None


class OpenTelemetryBackend:
    """Optional OTel API adapter; provider/exporter composition remains external."""

    def __init__(
        self,
        *,
        resource: TelemetryResource,
        scope: TelemetryInstrumentationScope,
        tracer_provider: Any | None = None,
        meter_provider: Any | None = None,
    ) -> None:
        trace_api, metrics_api, link_type = _load_otel_api()
        self.resource = resource
        self.scope = scope
        self.otel_resource = _build_otel_resource(resource)
        self._link_type = link_type
        self._trace_adapter = OpenTelemetryTraceAdapter()
        trace_owner = tracer_provider or trace_api
        meter_owner = meter_provider or metrics_api
        if tracer_provider is not None:
            _validate_provider_resource(tracer_provider, resource)
        if meter_provider is not None:
            _validate_provider_resource(meter_provider, resource)
        self._tracer = trace_owner.get_tracer(
            scope.name,
            scope.version,
            scope.schema_url,
        )
        self._meter = meter_owner.get_meter(
            scope.name,
            scope.version,
            scope.schema_url,
        )
        self._counters: dict[str, Any] = {}

    def start_span(
        self,
        name: str,
        *,
        attributes: Mapping[str, Any],
        links: tuple[TelemetrySpanLink, ...],
    ) -> AbstractContextManager[Any]:
        native_links = []
        for link in links:
            native_context = self._trace_adapter.to_native_context(link.context)
            if native_context is not None:
                native_links.append(
                    self._link_type(native_context, attributes=dict(link.attributes))
                )
        return self._tracer.start_as_current_span(
            name,
            attributes=dict(attributes),
            links=native_links,
            record_exception=False,
            set_status_on_exception=False,
        )

    def add_counter(
        self,
        name: str,
        value: int,
        *,
        attributes: Mapping[str, Any],
    ) -> None:
        counter = self._counters.get(name)
        if counter is None:
            counter = self._meter.create_counter(name)
            self._counters[name] = counter
        counter.add(value, attributes=dict(attributes))


class TelemetrySpan:
    def __init__(self, native_span: Any, policy: TelemetryAttributePolicy) -> None:
        self._native_span = native_span
        self._policy = policy

    def set_attributes(self, attributes: Mapping[str, Any]) -> None:
        for key, value in self._policy.span_attributes(attributes).items():
            try:
                self._native_span.set_attribute(key, value)
            except Exception:
                return

    def add_event(self, name: str, attributes: Mapping[str, Any] | None = None) -> None:
        if not isinstance(name, str) or not _IDENTITY_PATTERN.fullmatch(name):
            return
        try:
            self._native_span.add_event(
                name,
                attributes=dict(self._policy.span_attributes(attributes)),
            )
        except Exception:
            return

    def record_exception(self, error: BaseException) -> None:
        self.set_attributes({"newsroom.error.type": type(error).__name__[:96]})


class _SafeSpanScope(AbstractContextManager[TelemetrySpan]):
    def __init__(
        self,
        backend: TelemetryBackend,
        *,
        name: str,
        attributes: Mapping[str, Any],
        links: tuple[TelemetrySpanLink, ...],
        policy: TelemetryAttributePolicy,
    ) -> None:
        self._backend = backend
        self._name = name
        self._attributes = attributes
        self._links = links
        self._policy = policy
        self._native_scope: AbstractContextManager[Any] | None = None
        self._span: TelemetrySpan | None = None

    def __enter__(self) -> TelemetrySpan:
        try:
            self._native_scope = self._backend.start_span(
                self._name,
                attributes=self._attributes,
                links=self._links,
            )
            native_span = self._native_scope.__enter__()
        except Exception:
            self._native_scope = None
            native_span = _NoOpNativeSpan()
        self._span = TelemetrySpan(native_span, self._policy)
        return self._span

    def __exit__(self, exc_type: Any, exc: BaseException | None, traceback: Any) -> bool:
        if exc is not None and self._span is not None:
            self._span.record_exception(exc)
        if self._native_scope is not None:
            try:
                # Detach the OTel context without forwarding an untrusted
                # exception message or traceback to an arbitrary exporter.
                self._native_scope.__exit__(None, None, None)
            except Exception:
                pass
        return False


class EventTelemetry:
    """Failure-isolated telemetry facade that can never gate durable behavior."""

    def __init__(
        self,
        backend: TelemetryBackend,
        *,
        attribute_policy: TelemetryAttributePolicy | None = None,
        sampler: Callable[[str, Mapping[str, Any]], bool] | None = None,
    ) -> None:
        self._backend = backend
        self._attribute_policy = attribute_policy or DEFAULT_TELEMETRY_ATTRIBUTE_POLICY
        self._sampler = sampler
        self._resource = _backend_identity(
            backend,
            "resource",
            TelemetryResource(service_name="newsroom"),
            TelemetryResource,
        )
        self._scope = _backend_identity(
            backend,
            "scope",
            TelemetryInstrumentationScope(name="framework.events", version="1"),
            TelemetryInstrumentationScope,
        )

    @property
    def resource(self) -> TelemetryResource:
        return self._resource

    @property
    def scope(self) -> TelemetryInstrumentationScope:
        return self._scope

    def start_span(
        self,
        name: str,
        *,
        attributes: Mapping[str, Any] | None = None,
        links: tuple[TelemetrySpanLink | None, ...] = (),
    ) -> AbstractContextManager[TelemetrySpan]:
        try:
            safe_name = _identity(name, "span name")
        except (TypeError, ValueError):
            safe_name = "newsroom.telemetry.invalid"
        safe_attributes = self._attribute_policy.span_attributes(attributes)
        actual_links = tuple(link for link in links if link is not None)[:MAX_TELEMETRY_LINKS]
        if self._sampler is not None:
            try:
                sampled = bool(self._sampler(safe_name, safe_attributes))
            except Exception:
                sampled = False
            if not sampled:
                return _SafeSpanScope(
                    NoOpTelemetryBackend(resource=self.resource, scope=self.scope),
                    name=safe_name,
                    attributes=safe_attributes,
                    links=(),
                    policy=self._attribute_policy,
                )
        return _SafeSpanScope(
            self._backend,
            name=safe_name,
            attributes=safe_attributes,
            links=actual_links,
            policy=self._attribute_policy,
        )

    def add_counter(
        self,
        name: str,
        value: int = 1,
        *,
        labels: Mapping[str, Any] | None = None,
    ) -> None:
        allowed = _METRIC_LABELS.get(name)
        if allowed is None or isinstance(value, bool) or not isinstance(value, int):
            return
        raw_labels = labels if isinstance(labels, Mapping) else {}
        if any(key not in allowed for key in raw_labels):
            return
        projected: dict[str, Any] = {}
        for key, label_value in raw_labels.items():
            safe = _metric_label_value(str(key), label_value)
            if safe is None:
                return
            projected[str(key)] = safe
        try:
            self._backend.add_counter(
                name,
                value,
                attributes=MappingProxyType(projected),
            )
        except Exception:
            return


def default_event_telemetry(
    *,
    resource: TelemetryResource | None = None,
    scope: TelemetryInstrumentationScope | None = None,
    sampler: Callable[[str, Mapping[str, Any]], bool] | None = None,
) -> EventTelemetry:
    actual_resource = resource or TelemetryResource(service_name="newsroom")
    actual_scope = scope or TelemetryInstrumentationScope(
        name="framework.events",
        version="1",
    )
    try:
        backend: TelemetryBackend = OpenTelemetryBackend(
            resource=actual_resource,
            scope=actual_scope,
        )
    except Exception:
        backend = NoOpTelemetryBackend(
            resource=actual_resource,
            scope=actual_scope,
        )
    return EventTelemetry(backend, sampler=sampler)


def _attribute_value(value: Any, *, max_length: int) -> Any | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    if isinstance(value, float):
        return value if value == value and abs(value) != float("inf") else None
    if isinstance(value, str):
        if "\r" in value or "\n" in value or len(value) > max_length:
            return None
        return value
    return None


def _identity(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or _IDENTITY_PATTERN.fullmatch(value) is None:
        raise ValueError(f"{field_name} must be a bounded telemetry identity")
    return value


def _optional_identity(value: Any, field_name: str) -> str | None:
    if value is None:
        return None
    return _identity(value, field_name)


def _metric_label_value(key: str, value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    allowed = _METRIC_LABEL_VALUE_DOMAINS.get(key)
    if allowed is None or value not in allowed:
        return None
    return value


def _backend_identity(
    backend: Any,
    field_name: str,
    fallback: Any,
    expected_type: type[Any],
) -> Any:
    try:
        value = getattr(backend, field_name)
    except Exception:
        return fallback
    return value if isinstance(value, expected_type) else fallback


def _build_otel_resource(resource: TelemetryResource) -> Any:
    try:
        from opentelemetry.sdk.resources import Resource
    except Exception:
        return resource.to_attributes()
    return Resource.create(dict(resource.to_attributes()))


def _validate_provider_resource(provider: Any, resource: TelemetryResource) -> None:
    configured = getattr(provider, "resource", None)
    if configured is None:
        raise ValueError("OpenTelemetry provider must expose its Resource")
    attributes = getattr(configured, "attributes", configured)
    if not isinstance(attributes, Mapping):
        raise ValueError("OpenTelemetry provider Resource must expose attributes")
    expected = resource.to_attributes()
    if any(attributes.get(key) != value for key, value in expected.items()):
        raise ValueError("OpenTelemetry provider Resource does not match composition")


def _load_otel_api() -> tuple[Any, Any, Any]:
    from opentelemetry import metrics, trace
    from opentelemetry.trace import Link

    return trace, metrics, Link


__all__ = [
    "DEFAULT_TELEMETRY_ATTRIBUTE_POLICY",
    "EventTelemetry",
    "MAX_TELEMETRY_ATTRIBUTES",
    "MAX_TELEMETRY_ATTRIBUTE_LENGTH",
    "MAX_TELEMETRY_LINKS",
    "NoOpTelemetryBackend",
    "OpenTelemetryBackend",
    "TelemetryAttributePolicy",
    "TelemetryBackend",
    "TelemetryInstrumentationScope",
    "TelemetryResource",
    "TelemetrySpan",
    "TelemetrySpanLink",
    "default_event_telemetry",
]
