from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from framework.events.errors import (
    EventQuarantineError,
    EventSchemaError,
    EventSchemaValidationError,
    EventUnknownSchemaError,
    EventUpcastError,
)
from framework.events.schema import (
    EventSchemaCatalog,
    EventSchemaRegistration,
    FieldDisposition,
    SensitivityPolicy,
    default_event_schema_catalog,
)


_LEGACY_FIXTURES = Path(__file__).parents[2] / "fixtures" / "events" / "legacy"


def test_catalog_validates_without_exposing_instance_values() -> None:
    catalog = EventSchemaCatalog()
    catalog.register(
        EventSchemaRegistration(
            event_type="io.newsroom.test",
            data_schema="io.newsroom.test/v1",
            json_schema={
                "type": "object",
                "properties": {"count": {"type": "integer"}},
                "required": ["count"],
                "additionalProperties": False,
            },
            current=True,
        )
    )

    assert catalog.validate(
        "io.newsroom.test",
        "io.newsroom.test/v1",
        {"count": 2},
    ) == {"count": 2}

    secret = "never-include-this-instance-value"
    with pytest.raises(EventSchemaValidationError) as caught:
        catalog.validate(
            "io.newsroom.test",
            "io.newsroom.test/v1",
            {"count": secret},
        )

    assert caught.value.path == "$.count"
    assert caught.value.rule == "type"
    assert secret not in str(caught.value)


def test_catalog_rejects_unknown_duplicate_and_multiple_current_schemas() -> None:
    catalog = EventSchemaCatalog()
    registration = EventSchemaRegistration(
        event_type="io.newsroom.test",
        data_schema="io.newsroom.test/v1",
        json_schema={"type": "object"},
        current=True,
    )
    catalog.register(registration)

    with pytest.raises(EventSchemaError):
        catalog.register(registration)
    with pytest.raises(EventSchemaError):
        catalog.register(
            EventSchemaRegistration(
                event_type="io.newsroom.test",
                data_schema="io.newsroom.test/v2",
                json_schema={"type": "object"},
                current=True,
            )
        )
    with pytest.raises(EventUnknownSchemaError):
        catalog.validate("io.newsroom.unknown", "v1", {})


def test_catalog_applies_adjacent_pure_upcasters_and_validates_each_step() -> None:
    source = {"value": 2, "nested": {"stable": True}}
    catalog = EventSchemaCatalog()
    catalog.register(
        EventSchemaRegistration(
            event_type="io.newsroom.test",
            data_schema="v1",
            json_schema={
                "type": "object",
                "required": ["value", "nested"],
                "properties": {
                    "value": {"type": "integer"},
                    "nested": {"type": "object"},
                },
            },
            upcast_to="v2",
            upcaster=lambda payload: {**payload, "doubled": payload["value"] * 2},
        )
    )
    catalog.register(
        EventSchemaRegistration(
            event_type="io.newsroom.test",
            data_schema="v2",
            json_schema={
                "type": "object",
                "required": ["value", "nested", "doubled"],
                "properties": {
                    "value": {"type": "integer"},
                    "nested": {"type": "object"},
                    "doubled": {"type": "integer"},
                },
            },
            upcast_to="v3",
            upcaster=lambda payload: {**payload, "label": f"value-{payload['value']}"},
        )
    )
    catalog.register(
        EventSchemaRegistration(
            event_type="io.newsroom.test",
            data_schema="v3",
            json_schema={
                "type": "object",
                "required": ["value", "nested", "doubled", "label"],
                "properties": {
                    "value": {"type": "integer"},
                    "nested": {"type": "object"},
                    "doubled": {"type": "integer"},
                    "label": {"type": "string"},
                },
            },
            current=True,
        )
    )

    schema, payload, applied = catalog.upcast("io.newsroom.test", "v1", source)

    assert schema == "v3"
    assert payload == {
        "value": 2,
        "nested": {"stable": True},
        "doubled": 4,
        "label": "value-2",
    }
    assert applied == ("v1->v2", "v2->v3")
    assert source == {"value": 2, "nested": {"stable": True}}


def test_catalog_fails_closed_when_upcast_step_is_missing() -> None:
    catalog = EventSchemaCatalog()
    catalog.register(
        EventSchemaRegistration(
            event_type="io.newsroom.test",
            data_schema="v1",
            json_schema={"type": "object"},
        )
    )
    catalog.register(
        EventSchemaRegistration(
            event_type="io.newsroom.test",
            data_schema="v2",
            json_schema={"type": "object"},
            current=True,
        )
    )

    with pytest.raises(EventUpcastError):
        catalog.upcast("io.newsroom.test", "v1", {})


def test_upcaster_receives_recursively_immutable_input() -> None:
    def mutating_upcaster(payload: object) -> dict[str, object]:
        payload["nested"]["items"].append("mutated")  # type: ignore[index,union-attr]
        return dict(payload)  # pragma: no cover - mutation must fail first

    catalog = EventSchemaCatalog()
    catalog.register(
        EventSchemaRegistration(
            event_type="io.newsroom.test",
            data_schema="v1",
            json_schema={"type": "object"},
            upcast_to="v2",
            upcaster=mutating_upcaster,
        )
    )
    catalog.register(
        EventSchemaRegistration(
            event_type="io.newsroom.test",
            data_schema="v2",
            json_schema={"type": "object"},
            current=True,
        )
    )
    source = {"nested": {"items": ["original"]}}

    with pytest.raises(EventUpcastError):
        catalog.upcast("io.newsroom.test", "v1", source)

    assert source == {"nested": {"items": ["original"]}}


def test_default_catalog_registers_workflow_and_harness_aliases() -> None:
    catalog = default_event_schema_catalog()

    assert catalog.current_schema("workflow_started") == "newsroom.workflow-event/v1"
    assert catalog.current_schema("phase_recorded") == "newsroom.harness-event/v1"
    assert catalog.validate(
        "checkpoint_created",
        "newsroom.harness-event/v1",
        {"checkpoint_id": "cp-1"},
    ) == {"checkpoint_id": "cp-1"}
    assert catalog.validate(
        "workflow_started",
        "newsroom.workflow-event/v1",
        {"workflow_id": "wf-1", "workflow_version": "1", "profile": "live"},
    ) == {"workflow_id": "wf-1", "workflow_version": "1", "profile": "live"}


def test_default_catalog_uses_real_workflow_and_harness_payload_contracts() -> None:
    catalog = default_event_schema_catalog()

    assert catalog.validate(
        "phase_recorded",
        "newsroom.harness-event/v1",
        {
            "phase": "verify",
            "step_id": "collect",
            "input_refs": [],
            "output_refs": ["artifact://run/output.json"],
            "gate_results": [{"gate": "quality", "passed": True}],
            "metadata": {"turn_count": 2},
            "occurred_at": "2026-05-25T06:00:00Z",
        },
    )["phase"] == "verify"

    with pytest.raises(EventSchemaValidationError) as workflow_error:
        catalog.validate(
            "workflow_started",
            "newsroom.workflow-event/v1",
            {"profile": "live"},
        )
    assert workflow_error.value.rule == "anyOf"

    secret = "must-not-leak-as-invalid-status"
    with pytest.raises(EventSchemaValidationError) as harness_error:
        catalog.validate(
            "gate_evaluated",
            "newsroom.harness-event/v1",
            {"gate": "quality", "passed": secret, "details": {}},
        )
    assert harness_error.value.path == "$.passed"
    assert secret not in str(harness_error.value)


def test_default_catalog_registers_schema_owned_sensitivity_policies() -> None:
    catalog = default_event_schema_catalog()

    stream_policy = catalog.get(
        "agent_llm_stream_event",
        "newsroom.workflow-event/v1",
    ).sensitivity_policy
    worker_policy = catalog.get(
        "worker_called",
        "newsroom.harness-event/v1",
    ).sensitivity_policy

    assert stream_policy.disposition_for("/stream_event") is FieldDisposition.REFERENCE_ONLY
    assert stream_policy.allow_payload_reference is True
    assert worker_policy.disposition_for("/inputs") is FieldDisposition.REFERENCE_ONLY


def test_registration_rejects_non_adjacent_and_impure_upcasters() -> None:
    with pytest.raises(EventSchemaError, match="adjacent"):
        EventSchemaRegistration(
            event_type="io.newsroom.test",
            data_schema="io.newsroom.test/v1",
            json_schema={"type": "object"},
            upcast_to="io.newsroom.test/v3",
            upcaster=lambda payload: dict(payload),
        )

    def reads_file(payload: object) -> dict[str, object]:
        Path(__file__).read_text(encoding="utf-8")
        return dict(payload)  # pragma: no cover - registration rejects the function

    with pytest.raises(EventSchemaError, match="forbidden"):
        EventSchemaRegistration(
            event_type="io.newsroom.test",
            data_schema="io.newsroom.test/v1",
            json_schema={"type": "object"},
            upcast_to="io.newsroom.test/v2",
            upcaster=reads_file,
        )

    def reads_clock(payload: object) -> dict[str, object]:
        return {**dict(payload), "observed": datetime.now(timezone.utc).isoformat()}

    with pytest.raises(EventSchemaError, match="forbidden"):
        EventSchemaRegistration(
            event_type="io.newsroom.test",
            data_schema="io.newsroom.test/v1",
            json_schema={"type": "object"},
            upcast_to="io.newsroom.test/v2",
            upcaster=reads_clock,
        )


def test_historical_fixture_upcasts_without_rewriting_source() -> None:
    fixture_path = _LEGACY_FIXTURES / "valid" / "schema_upcast_v1.jsonl"
    source_bytes = fixture_path.read_bytes()
    record = json.loads(source_bytes)
    catalog = EventSchemaCatalog()
    catalog.register(
        EventSchemaRegistration(
            event_type=record["event_type"],
            data_schema="io.newsroom.fixture/v1",
            json_schema={
                "type": "object",
                "required": ["count"],
                "properties": {"count": {"type": "integer"}},
                "additionalProperties": False,
            },
            upcast_to="io.newsroom.fixture/v2",
            upcaster=lambda payload: {**payload, "doubled": payload["count"] * 2},
        )
    )
    catalog.register(
        EventSchemaRegistration(
            event_type=record["event_type"],
            data_schema="io.newsroom.fixture/v2",
            json_schema={
                "type": "object",
                "required": ["count", "doubled"],
                "properties": {
                    "count": {"type": "integer"},
                    "doubled": {"type": "integer"},
                },
                "additionalProperties": False,
            },
            current=True,
        )
    )

    resolved = catalog.resolve_historical(
        record["event_type"],
        record["data_schema"],
        record["payload"],
        occurred_at=record["occurred_at"],
        source=str(fixture_path),
    )

    assert resolved.data_schema == "io.newsroom.fixture/v2"
    assert resolved.payload_copy() == {"count": 2, "doubled": 4}
    assert resolved.applied_upcasters == (
        "io.newsroom.fixture/v1->io.newsroom.fixture/v2",
    )
    assert resolved.occurred_at.isoformat() == "2026-05-25T06:05:00+00:00"
    assert fixture_path.read_bytes() == source_bytes


def test_historical_unknown_version_and_missing_time_are_quarantined() -> None:
    catalog = default_event_schema_catalog()
    unknown_path = _LEGACY_FIXTURES / "invalid" / "unknown_schema.jsonl"
    unknown = json.loads(unknown_path.read_text(encoding="utf-8"))
    with pytest.raises(EventQuarantineError) as unknown_error:
        catalog.resolve_historical(
            unknown["event_type"],
            "newsroom.workflow-event/v1",
            unknown["payload"],
            occurred_at=unknown["occurred_at"],
            envelope_schema=unknown["schema_version"],
            source=str(unknown_path),
        )
    assert unknown_error.value.reason == "unknown_envelope_schema"

    missing_path = _LEGACY_FIXTURES / "invalid" / "missing_time_record_v1.jsonl"
    missing = json.loads(missing_path.read_text(encoding="utf-8"))
    with pytest.raises(EventQuarantineError) as missing_error:
        catalog.resolve_historical(
            missing["event_type"],
            "newsroom.workflow-event/v1",
            missing["payload"],
            occurred_at=missing.get("occurred_at"),
            envelope_schema=missing["schema_version"],
            source=str(missing_path),
        )
    assert missing_error.value.reason == "missing_occurred_at"

    with pytest.raises(EventQuarantineError) as data_schema_error:
        catalog.resolve_historical(
            "workflow_started",
            "newsroom.workflow-event/v999",
            {"run_id": "run-unknown-data-schema"},
            occurred_at="2026-05-25T06:01:00Z",
            envelope_schema="newsroom.event_record.v1",
            source="legacy.jsonl:9",
        )
    assert data_schema_error.value.reason == "unknown_data_schema"


@pytest.mark.parametrize(
    "occurred_at",
    ["2026-05-25T06:01:00", datetime(2026, 5, 25, 6, 1)],
)
def test_historical_time_without_explicit_timezone_is_quarantined(
    occurred_at: str | datetime,
) -> None:
    with pytest.raises(EventQuarantineError) as caught:
        default_event_schema_catalog().resolve_historical(
            "workflow_started",
            "newsroom.workflow-event/v1",
            {"run_id": "run-naive-time"},
            occurred_at=occurred_at,
            envelope_schema="newsroom.event_record.v1",
            source="legacy-naive-time.jsonl:1",
        )

    assert caught.value.reason == "invalid_occurred_at"


def test_historical_upcaster_failure_is_quarantined_without_payload_diagnostic() -> None:
    fixture_path = _LEGACY_FIXTURES / "invalid" / "upcast_failure.jsonl"
    record = json.loads(fixture_path.read_text(encoding="utf-8"))
    secret = record["payload"]["diagnostic_secret"]

    def failing_upcaster(payload: object) -> dict[str, object]:
        raise RuntimeError("upcaster could not convert historical payload")

    catalog = EventSchemaCatalog()
    catalog.register(
        EventSchemaRegistration(
            event_type=record["event_type"],
            data_schema="io.newsroom.fixture/v1",
            json_schema={"type": "object"},
            upcast_to="io.newsroom.fixture/v2",
            upcaster=failing_upcaster,
        )
    )
    catalog.register(
        EventSchemaRegistration(
            event_type=record["event_type"],
            data_schema="io.newsroom.fixture/v2",
            json_schema={"type": "object"},
            current=True,
        )
    )

    with pytest.raises(EventQuarantineError) as caught:
        catalog.resolve_historical(
            record["event_type"],
            record["data_schema"],
            record["payload"],
            occurred_at=record["occurred_at"],
            source=str(fixture_path),
        )

    assert caught.value.reason == "upcast_failed"
    assert secret not in str(caught.value)


def test_registration_freezes_schema_and_policy_inputs() -> None:
    schema = {"type": "object", "properties": {"value": {"type": "string"}}}
    rules = {"/value": "sensitive"}
    policy = SensitivityPolicy(field_rules=rules)
    registration = EventSchemaRegistration(
        event_type="io.newsroom.test",
        data_schema="v1",
        json_schema=schema,
        sensitivity_policy=policy,
        current=True,
    )
    schema["properties"]["value"]["type"] = "integer"
    rules["/value"] = "allowed"

    assert registration.schema_copy()["properties"]["value"]["type"] == "string"
    assert registration.sensitivity_policy.disposition_for("/value") == "sensitive"
