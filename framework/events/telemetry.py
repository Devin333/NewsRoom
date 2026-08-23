from __future__ import annotations

from collections.abc import Callable, Mapping
from contextlib import AbstractContextManager
from dataclasses import dataclass, field
from math import isfinite
import re
from threading import RLock
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
        "event_append_latency_seconds": frozenset({"backend"}),
        "event_delivery_pending": frozenset({"consumer"}),
        "event_delivery_lag": frozenset({"consumer"}),
        "event_delivery_oldest_age_seconds": frozenset({"consumer"}),
        "event_delivery_attempt_total": frozenset({"consumer", "outcome"}),
        "event_dead_letter_total": frozenset({"consumer", "reason_class"}),
        "event_lease_recovery_total": frozenset({"consumer"}),
        "event_quarantine_total": frozenset({"reason"}),
        "event_replay_total": frozenset({"mode", "result"}),
        "event_replay_mismatch_total": frozenset({"reason"}),
        "event_schema_validation_total": frozenset({"event_type", "result"}),
        "event_upcast_total": frozenset({"event_type", "from", "to", "result"}),
        "event_identity_collision_total": frozenset({"source"}),
        "event_projection_high_watermark": frozenset({"projection"}),
        "event_projection_staleness": frozenset({"projection"}),
        "event_store_health": frozenset({"backend"}),
        "trace_propagation_total": frozenset({"boundary", "result"}),
    }
)
_COUNTER_METRICS = frozenset(
    {
        "event_append_total",
        "event_delivery_attempt_total",
        "event_dead_letter_total",
        "event_lease_recovery_total",
        "event_quarantine_total",
        "event_replay_total",
        "event_replay_mismatch_total",
        "event_schema_validation_total",
        "event_upcast_total",
        "event_identity_collision_total",
        "trace_propagation_total",
    }
)
_HISTOGRAM_METRICS = frozenset({"event_append_latency_seconds"})
_GAUGE_METRICS = frozenset(
    {
        "event_delivery_pending",
        "event_delivery_lag",
        "event_delivery_oldest_age_seconds",
        "event_projection_high_watermark",
        "event_projection_staleness",
        "event_store_health",
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
            {"audit", "graph", "harness", "projection", "telemetry", "unknown"}
        ),
        "event_type": frozenset({"registered", "unknown"}),
        "from": frozenset(
            {"unknown", "other", *(f"v{index}" for index in range(1, 11))}
        ),
        "mode": frozenset({"rebuild_state", "redeliver", "verify_history"}),
        "outcome": frozenset(
            {"ack", "dead_letter", "drop", "failed", "retry", "unknown"}
        ),
        "reason": frozenset(
            {
                "activity",
                "command",
                "conflict",
                "integrity",
                "missing_time",
                "schema",
                "security",
                "version",
                "unknown",
            }
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
        "projection": frozenset({"graph", "harness", "unknown"}),
        "source": frozenset(
            {"api", "graph", "harness", "migration", "tool", "unknown"}
        ),
        "to": frozenset(
            {"unknown", "other", *(f"v{index}" for index in range(1, 11))}
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

    def record_histogram(
        self,
        name: str,
        value: float,
        *,
        attributes: Mapping[str, Any],
    ) -> None: ...

    def record_gauge(
        self,
        name: str,
        value: float,
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

    def record_histogram(
        self,
        name: str,
        value: float,
        *,
        attributes: Mapping[str, Any],
    ) -> None:
        return None

    def record_gauge(
        self,
        name: str,
        value: float,
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
        self._observation_type = getattr(metrics_api, "Observation", None)
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
        self._histograms: dict[str, Any] = {}
        self._gauges: dict[str, Any] = {}
        self._gauge_values: dict[
            str,
            dict[tuple[tuple[str, str], ...], float],
        ] = {}
        self._gauge_lock = RLock()

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

    def record_histogram(
        self,
        name: str,
        value: float,
        *,
        attributes: Mapping[str, Any],
    ) -> None:
        histogram = self._histograms.get(name)
        if histogram is None:
            histogram = self._meter.create_histogram(name)
            self._histograms[name] = histogram
        histogram.record(value, attributes=dict(attributes))

    def record_gauge(
        self,
        name: str,
        value: float,
        *,
        attributes: Mapping[str, Any],
    ) -> None:
        label_key = tuple(sorted((str(key), str(item)) for key, item in attributes.items()))
        with self._gauge_lock:
            values = self._gauge_values.setdefault(name, {})
            values[label_key] = value
            if name in self._gauges:
                return
            if self._observation_type is None:
                raise RuntimeError("OpenTelemetry Observation API is unavailable")
            self._gauges[name] = self._meter.create_observable_gauge(
                name,
                callbacks=(self._gauge_callback(name),),
            )

    def _gauge_callback(self, name: str) -> Callable[[Any], tuple[Any, ...]]:
        def observe(_options: Any) -> tuple[Any, ...]:
            with self._gauge_lock:
                values = tuple(self._gauge_values.get(name, {}).items())
            observation_type = self._observation_type
            if observation_type is None:
                return ()
            return tuple(
                observation_type(value, attributes=dict(label_key))
                for label_key, value in values
            )

        return observe


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
        if name not in _COUNTER_METRICS or isinstance(value, bool) or not isinstance(value, int):
            return
        if value <= 0:
            return
        projected = _metric_labels(name, labels)
        if projected is None:
            return
        try:
            self._backend.add_counter(
                name,
                value,
                attributes=MappingProxyType(projected),
            )
        except Exception:
            return

    def record_histogram(
        self,
        name: str,
        value: float,
        *,
        labels: Mapping[str, Any] | None = None,
    ) -> None:
        if name not in _HISTOGRAM_METRICS:
            return
        measurement = _nonnegative_measurement(value)
        projected = _metric_labels(name, labels)
        if measurement is None or projected is None:
            return
        try:
            self._backend.record_histogram(
                name,
                measurement,
                attributes=MappingProxyType(projected),
            )
        except Exception:
            return

    def record_gauge(
        self,
        name: str,
        value: float,
        *,
        labels: Mapping[str, Any] | None = None,
    ) -> None:
        if name not in _GAUGE_METRICS:
            return
        measurement = _nonnegative_measurement(value)
        projected = _metric_labels(name, labels)
        if measurement is None or projected is None:
            return
        try:
            self._backend.record_gauge(
                name,
                measurement,
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


def _metric_labels(
    name: str,
    labels: Mapping[str, Any] | None,
) -> dict[str, str] | None:
    allowed = _METRIC_LABELS.get(name)
    if allowed is None:
        return None
    raw_labels = labels if isinstance(labels, Mapping) else {}
    if frozenset(str(key) for key in raw_labels) != allowed:
        return None
    projected: dict[str, str] = {}
    for key, label_value in raw_labels.items():
        normalized_key = str(key)
        safe = _metric_label_value(normalized_key, label_value)
        if safe is None:
            return None
        projected[normalized_key] = safe
    return projected


def _nonnegative_measurement(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    measurement = float(value)
    if not isfinite(measurement) or measurement < 0:
        return None
    return measurement


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
