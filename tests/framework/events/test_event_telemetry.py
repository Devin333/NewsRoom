from __future__ import annotations

from contextlib import AbstractContextManager
from types import SimpleNamespace
from typing import Any

import pytest

from framework.events.telemetry import (
    EventTelemetry,
    MAX_TELEMETRY_LINKS,
    NoOpTelemetryBackend,
    OpenTelemetryBackend,
    TelemetryInstrumentationScope,
    TelemetryResource,
    TelemetrySpanLink,
    default_event_telemetry,
)
from framework.events.trace import TraceContext
import framework.events.telemetry as telemetry_module


class _CapturedSpan:
    def __init__(self) -> None:
        self.attributes: dict[str, Any] = {}
        self.events: list[tuple[str, dict[str, Any]]] = []

    def set_attribute(self, key: str, value: Any) -> None:
        self.attributes[key] = value

    def add_event(self, name: str, *, attributes: dict[str, Any]) -> None:
        self.events.append((name, dict(attributes)))


class _CapturedScope(AbstractContextManager[_CapturedSpan]):
    def __init__(self, span: _CapturedSpan, *, fail_exit: bool = False) -> None:
        self._span = span
        self._fail_exit = fail_exit
        self.exit_args: list[tuple[Any, BaseException | None, Any]] = []

    def __enter__(self) -> _CapturedSpan:
        return self._span

    def __exit__(self, exc_type: Any, exc: BaseException | None, traceback: Any) -> bool:
        self.exit_args.append((exc_type, exc, traceback))
        if self._fail_exit:
            raise RuntimeError("exporter failed")
        return False


class _CapturedBackend:
    def __init__(self, *, fail_start: bool = False, fail_exit: bool = False) -> None:
        self.resource = TelemetryResource(
            service_name="newsroom-worker",
            service_version="1",
            service_instance_id="worker-a",
        )
        self.scope = TelemetryInstrumentationScope(
            name="framework.events.delivery",
            version="1",
        )
        self.fail_start = fail_start
        self.fail_exit = fail_exit
        self.span = _CapturedSpan()
        self.scopes: list[_CapturedScope] = []
        self.started: list[dict[str, Any]] = []
        self.counters: list[tuple[str, int, dict[str, Any]]] = []
        self.histograms: list[tuple[str, float, dict[str, Any]]] = []
        self.gauges: list[tuple[str, float, dict[str, Any]]] = []

    def start_span(self, name: str, *, attributes: Any, links: Any):
        if self.fail_start:
            raise RuntimeError("tracer unavailable")
        self.started.append(
            {"name": name, "attributes": dict(attributes), "links": tuple(links)}
        )
        scope = _CapturedScope(self.span, fail_exit=self.fail_exit)
        self.scopes.append(scope)
        return scope

    def add_counter(self, name: str, value: int, *, attributes: Any) -> None:
        self.counters.append((name, value, dict(attributes)))

    def record_histogram(self, name: str, value: float, *, attributes: Any) -> None:
        self.histograms.append((name, value, dict(attributes)))

    def record_gauge(self, name: str, value: float, *, attributes: Any) -> None:
        self.gauges.append((name, value, dict(attributes)))


def test_resource_and_instrumentation_scope_have_distinct_ownership() -> None:
    resource = TelemetryResource(
        service_name="newsroom-api",
        service_version="2",
        service_instance_id="process-1",
        deployment_environment="test",
    )
    scope = TelemetryInstrumentationScope(
        name="interfaces.api",
        version="3",
        schema_url="https://opentelemetry.io/schemas/1.25.0",
    )

    assert dict(resource.to_attributes()) == {
        "service.name": "newsroom-api",
        "service.version": "2",
        "service.instance.id": "process-1",
        "deployment.environment.name": "test",
    }
    assert scope.name == "interfaces.api"
    assert "run_id" not in resource.to_attributes()


def test_telemetry_projects_only_schema_defined_low_cardinality_attributes() -> None:
    backend = _CapturedBackend()
    telemetry = EventTelemetry(backend)

    with telemetry.start_span(
        "newsroom.event.delivery",
        attributes={
            "newsroom.component": "delivery",
            "newsroom.event.type": "workflow_step_completed",
            "newsroom.outcome": "acked",
            "run_id": "run-secret",
            "tenant_id": "tenant-secret",
            "trace_id": "1" * 32,
            "event_id": "event-secret",
            "payload": {"password": "raw-secret"},
            "prompt": "raw prompt",
        },
    ):
        pass

    assert backend.started[0]["attributes"] == {
        "newsroom.component": "delivery",
        "newsroom.event.type": "workflow_step_completed",
        "newsroom.outcome": "acked",
    }
    serialized = repr(backend.started)
    assert "run-secret" not in serialized
    assert "tenant-secret" not in serialized
    assert "event-secret" not in serialized
    assert "raw-secret" not in serialized
    assert "raw prompt" not in serialized


def test_span_links_preserve_async_causality_without_business_ids() -> None:
    backend = _CapturedBackend()
    telemetry = EventTelemetry(backend)
    contexts = [
        TraceContext.root(
            run_id=f"run-{index}",
            trace_id=f"{index + 1:032x}",
            span_id=f"{index + 1:016x}",
        )
        for index in range(MAX_TELEMETRY_LINKS + 5)
    ]
    links = tuple(
        TelemetrySpanLink.from_context(context, relationship="batch_item")
        for context in contexts
    )

    with telemetry.start_span(
        "newsroom.event.batch",
        attributes={"newsroom.batch.size": len(contexts)},
        links=links,
    ):
        pass

    captured_links = backend.started[0]["links"]
    assert len(captured_links) == MAX_TELEMETRY_LINKS
    assert all("run_id" not in link.attributes for link in captured_links)
    assert all(
        link.attributes["newsroom.link.relationship"] == "batch_item"
        for link in captured_links
    )


@pytest.mark.parametrize("fail_start,fail_exit", [(True, False), (False, True)])
def test_tracer_or_exporter_failure_never_changes_durable_behavior(
    fail_start: bool,
    fail_exit: bool,
) -> None:
    telemetry = EventTelemetry(
        _CapturedBackend(fail_start=fail_start, fail_exit=fail_exit)
    )
    committed: list[str] = []

    with telemetry.start_span("newsroom.event.append"):
        committed.append("durable-event")

    assert committed == ["durable-event"]


def test_sampling_drop_never_skips_business_callback() -> None:
    backend = _CapturedBackend()
    telemetry = EventTelemetry(backend, sampler=lambda _name, _attrs: False)
    completed: list[str] = []

    with telemetry.start_span("newsroom.event.replay"):
        completed.append("replayed")

    assert completed == ["replayed"]
    assert backend.started == []


def test_sampling_drop_uses_safe_identity_when_backend_omits_optional_fields() -> None:
    backend = _ProtocolOnlyBackend()
    telemetry = EventTelemetry(backend, sampler=lambda _name, _attrs: False)
    completed: list[str] = []

    with telemetry.start_span("newsroom.event.delivery"):
        completed.append("delivered")

    assert completed == ["delivered"]
    assert backend.started == 0
    assert telemetry.resource.service_name == "newsroom"
    assert telemetry.scope.name == "framework.events"


def test_metric_contract_rejects_high_cardinality_or_unknown_labels() -> None:
    backend = _CapturedBackend()
    telemetry = EventTelemetry(backend)

    telemetry.add_counter(
        "event_delivery_attempt_total",
        labels={"consumer": "projection", "outcome": "ack"},
    )
    telemetry.add_counter(
        "event_delivery_attempt_total",
        labels={"consumer": "projection", "run_id": "run-secret"},
    )
    telemetry.add_counter(
        "unregistered_metric",
        labels={"tenant_id": "tenant-secret"},
    )
    telemetry.add_counter(
        "event_delivery_attempt_total",
        labels={"consumer": "tenant-specific-consumer", "outcome": "ack"},
    )

    assert backend.counters == [
        (
            "event_delivery_attempt_total",
            1,
            {"consumer": "projection", "outcome": "ack"},
        )
    ]


def test_operational_metric_contract_supports_histograms_and_current_gauges() -> None:
    backend = _CapturedBackend()
    telemetry = EventTelemetry(backend)

    telemetry.record_histogram(
        "event_append_latency_seconds",
        0.125,
        labels={"backend": "sqlite"},
    )
    telemetry.record_gauge(
        "event_delivery_pending",
        12,
        labels={"consumer": "workflow"},
    )
    telemetry.record_gauge(
        "event_store_health",
        1,
        labels={"backend": "postgresql"},
    )
    telemetry.record_gauge(
        "event_delivery_pending",
        99,
        labels={"consumer": "workflow", "run_id": "run-secret"},
    )
    telemetry.record_histogram(
        "event_append_latency_seconds",
        float("nan"),
        labels={"backend": "sqlite"},
    )

    assert backend.histograms == [
        ("event_append_latency_seconds", 0.125, {"backend": "sqlite"})
    ]
    assert backend.gauges == [
        ("event_delivery_pending", 12.0, {"consumer": "workflow"}),
        ("event_store_health", 1.0, {"backend": "postgresql"}),
    ]


def test_all_required_operational_metric_names_have_low_cardinality_contracts() -> None:
    backend = _CapturedBackend()
    telemetry = EventTelemetry(backend)

    counters = (
        ("event_append_total", {"backend": "sqlite", "result": "accepted"}),
        ("event_delivery_attempt_total", {"consumer": "workflow", "outcome": "ack"}),
        ("event_dead_letter_total", {"consumer": "workflow", "reason_class": "permanent"}),
        ("event_lease_recovery_total", {"consumer": "workflow"}),
        ("event_schema_validation_total", {"event_type": "registered", "result": "success"}),
        (
            "event_upcast_total",
            {"event_type": "registered", "from": "v1", "to": "v2", "result": "success"},
        ),
        ("event_quarantine_total", {"reason": "schema"}),
        ("event_identity_collision_total", {"source": "workflow"}),
        ("event_replay_total", {"mode": "rebuild_state", "result": "success"}),
        ("event_replay_mismatch_total", {"reason": "command"}),
    )
    for name, labels in counters:
        telemetry.add_counter(name, labels=labels)
    for name, labels in (
        ("event_delivery_lag", {"consumer": "workflow"}),
        ("event_delivery_oldest_age_seconds", {"consumer": "workflow"}),
        ("event_projection_high_watermark", {"projection": "workflow"}),
        ("event_projection_staleness", {"projection": "workflow"}),
    ):
        telemetry.record_gauge(name, 1, labels=labels)

    assert [item[0] for item in backend.counters] == [item[0] for item in counters]
    assert [item[0] for item in backend.gauges] == [
        "event_delivery_lag",
        "event_delivery_oldest_age_seconds",
        "event_projection_high_watermark",
        "event_projection_staleness",
    ]


def test_native_span_never_receives_raw_exception_or_traceback() -> None:
    backend = _CapturedBackend()
    telemetry = EventTelemetry(backend)
    secret = "Bearer raw-secret-token"

    with pytest.raises(RuntimeError, match="raw-secret-token"):
        with telemetry.start_span("newsroom.event.delivery"):
            raise RuntimeError(secret)

    assert backend.scopes[0].exit_args == [(None, None, None)]
    assert backend.span.attributes == {"newsroom.error.type": "RuntimeError"}
    assert secret not in repr(backend.span.attributes)


def test_otel_provider_resource_must_match_composed_resource(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    trace_api = _Provider({"service.name": "newsroom-default"})
    metrics_api = _Provider({"service.name": "newsroom-default"})
    monkeypatch.setattr(
        telemetry_module,
        "_load_otel_api",
        lambda: (trace_api, metrics_api, object),
    )
    monkeypatch.setattr(
        telemetry_module,
        "_build_otel_resource",
        lambda resource: resource.to_attributes(),
    )
    monkeypatch.setattr(
        telemetry_module,
        "OpenTelemetryTraceAdapter",
        lambda: object(),
    )
    resource = TelemetryResource(service_name="newsroom-api")
    scope = TelemetryInstrumentationScope(name="interfaces.api", version="1")
    mismatched = _Provider({"service.name": "other-service"})

    with pytest.raises(ValueError, match="does not match composition"):
        OpenTelemetryBackend(
            resource=resource,
            scope=scope,
            tracer_provider=mismatched,
            meter_provider=_Provider(dict(resource.to_attributes())),
        )

    matching_trace = _Provider(dict(resource.to_attributes()))
    matching_meter = _Provider(dict(resource.to_attributes()))
    backend = OpenTelemetryBackend(
        resource=resource,
        scope=scope,
        tracer_provider=matching_trace,
        meter_provider=matching_meter,
    )

    assert backend.resource == resource
    assert matching_trace.requested == [("interfaces.api", "1", None)]
    assert matching_meter.requested == [("interfaces.api", "1", None)]


def test_otel_backend_caches_instruments_and_exposes_latest_observable_gauge(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    resource = TelemetryResource(service_name="newsroom-api")
    scope = TelemetryInstrumentationScope(name="interfaces.api", version="1")
    trace_provider = _Provider(dict(resource.to_attributes()))
    meter_provider = _MetricProvider(dict(resource.to_attributes()))
    metrics_api = SimpleNamespace(Observation=_Observation)
    monkeypatch.setattr(
        telemetry_module,
        "_load_otel_api",
        lambda: (trace_provider, metrics_api, object),
    )
    monkeypatch.setattr(
        telemetry_module,
        "_build_otel_resource",
        lambda value: value.to_attributes(),
    )
    monkeypatch.setattr(
        telemetry_module,
        "OpenTelemetryTraceAdapter",
        lambda: object(),
    )
    backend = OpenTelemetryBackend(
        resource=resource,
        scope=scope,
        tracer_provider=trace_provider,
        meter_provider=meter_provider,
    )

    backend.add_counter(
        "event_append_total",
        1,
        attributes={"backend": "sqlite", "result": "accepted"},
    )
    backend.record_histogram(
        "event_append_latency_seconds",
        0.25,
        attributes={"backend": "sqlite"},
    )
    backend.record_gauge(
        "event_store_health",
        0,
        attributes={"backend": "sqlite"},
    )
    backend.record_gauge(
        "event_store_health",
        1,
        attributes={"backend": "sqlite"},
    )

    assert meter_provider.meter.counters["event_append_total"].values == [
        (1, {"backend": "sqlite", "result": "accepted"})
    ]
    assert meter_provider.meter.histograms[
        "event_append_latency_seconds"
    ].values == [(0.25, {"backend": "sqlite"})]
    observations = meter_provider.meter.gauge_callbacks[
        "event_store_health"
    ](None)
    assert observations == (
        _Observation(1, {"backend": "sqlite"}),
    )


def test_missing_otel_dependency_selects_noop_backend(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _missing() -> tuple[object, object, object]:
        raise ImportError("optional dependency unavailable")

    monkeypatch.setattr(telemetry_module, "_load_otel_api", _missing)

    telemetry = default_event_telemetry()

    assert isinstance(telemetry._backend, NoOpTelemetryBackend)
    with telemetry.start_span("newsroom.event.noop"):
        pass


class _Provider:
    def __init__(self, attributes: dict[str, str]) -> None:
        self.resource = SimpleNamespace(attributes=dict(attributes))
        self.requested: list[tuple[str, str | None, str | None]] = []

    def get_tracer(
        self,
        name: str,
        version: str | None,
        schema_url: str | None,
    ) -> object:
        self.requested.append((name, version, schema_url))
        return object()

    def get_meter(
        self,
        name: str,
        version: str | None,
        schema_url: str | None,
    ) -> object:
        self.requested.append((name, version, schema_url))
        return object()


class _RecordedInstrument:
    def __init__(self) -> None:
        self.values: list[tuple[float, dict[str, str]]] = []

    def add(self, value: int, *, attributes: dict[str, str]) -> None:
        self.values.append((value, dict(attributes)))

    def record(self, value: float, *, attributes: dict[str, str]) -> None:
        self.values.append((value, dict(attributes)))


class _MetricMeter:
    def __init__(self) -> None:
        self.counters: dict[str, _RecordedInstrument] = {}
        self.histograms: dict[str, _RecordedInstrument] = {}
        self.gauge_callbacks: dict[str, Any] = {}

    def create_counter(self, name: str) -> _RecordedInstrument:
        return self.counters.setdefault(name, _RecordedInstrument())

    def create_histogram(self, name: str) -> _RecordedInstrument:
        return self.histograms.setdefault(name, _RecordedInstrument())

    def create_observable_gauge(self, name: str, *, callbacks: tuple[Any, ...]):
        self.gauge_callbacks[name] = callbacks[0]
        return object()


class _MetricProvider(_Provider):
    def __init__(self, attributes: dict[str, str]) -> None:
        super().__init__(attributes)
        self.meter = _MetricMeter()

    def get_meter(
        self,
        name: str,
        version: str | None,
        schema_url: str | None,
    ) -> _MetricMeter:
        self.requested.append((name, version, schema_url))
        return self.meter


class _Observation:
    def __init__(self, value: float, attributes: dict[str, str]) -> None:
        self.value = value
        self.attributes = dict(attributes)

    def __eq__(self, other: object) -> bool:
        return (
            isinstance(other, _Observation)
            and self.value == other.value
            and self.attributes == other.attributes
        )


class _ProtocolOnlyBackend:
    def __init__(self) -> None:
        self.started = 0

    def start_span(self, name: str, *, attributes: Any, links: Any):
        self.started += 1
        raise AssertionError("sampled span must not reach the backend")

    def add_counter(self, name: str, value: int, *, attributes: Any) -> None:
        return None
