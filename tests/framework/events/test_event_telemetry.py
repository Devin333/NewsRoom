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


class _ProtocolOnlyBackend:
    def __init__(self) -> None:
        self.started = 0

    def start_span(self, name: str, *, attributes: Any, links: Any):
        self.started += 1
        raise AssertionError("sampled span must not reach the backend")

    def add_counter(self, name: str, value: int, *, attributes: Any) -> None:
        return None
