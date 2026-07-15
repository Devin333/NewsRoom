from __future__ import annotations

import json
import os
import subprocess
import sys
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
    WholeDocumentReferenceDisposition,
    default_event_schema_catalog,
)
from framework.events.schema.catalog import _run_pure_validator


_LEGACY_FIXTURES = Path(__file__).parents[2] / "fixtures" / "events" / "legacy"
ROOT = Path(__file__).resolve().parents[3]


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


def test_registration_rejects_upcaster_mutation_method_before_execution() -> None:
    def mutating_upcaster(payload: object) -> dict[str, object]:
        payload["nested"]["items"].append("mutated")  # type: ignore[index,union-attr]
        return dict(payload)  # pragma: no cover - mutation must fail first

    with pytest.raises(EventSchemaError, match="forbidden attribute: append"):
        EventSchemaRegistration(
            event_type="io.newsroom.test",
            data_schema="v1",
            json_schema={"type": "object"},
            upcast_to="v2",
            upcaster=mutating_upcaster,
        )


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


def test_default_catalog_accepts_harness_safe_summary_contracts() -> None:
    catalog = default_event_schema_catalog()
    summaries = {
        "decision_recorded": {
            "projection_schema": "harness-safe-summary/v1",
            "decision_type": "retry_step",
            "step_id": "collect",
            "target_step_id": None,
            "reason_ref": "sha256:" + "1" * 64,
            "decision_payload": {
                "backoff_seconds": 1,
                "decision_payload_ref": "sha256:" + "2" * 64,
            },
            "decided_by": "harness",
            "decided_at": "2026-07-15T08:00:00Z",
        },
        "worker_called": {
            "projection_schema": "harness-safe-summary/v1",
            "worker_type": "llm",
            "input_ref": "sha256:" + "3" * 64,
            "input_count": 1,
            "metadata_ref": "sha256:" + "4" * 64,
        },
        "worker_result_recorded": {
            "projection_schema": "harness-safe-summary/v1",
            "status": "succeeded",
            "output_ref": "sha256:" + "5" * 64,
            "diagnostics_ref": "sha256:" + "6" * 64,
            "metric_count": 1,
            "artifact_count": 0,
            "artifact_ref_checksums": [],
        },
        "gate_evaluated": {
            "projection_schema": "harness-safe-summary/v1",
            "gate": "quality",
            "passed": True,
            "details_ref": "sha256:" + "7" * 64,
        },
    }

    for event_type, payload in summaries.items():
        assert catalog.validate(
            event_type,
            "newsroom.harness-event/v1",
            payload,
        ) == payload

    with pytest.raises(EventSchemaValidationError) as invalid_ref:
        catalog.validate(
            "worker_called",
            "newsroom.harness-event/v1",
            {
                **summaries["worker_called"],
                "input_ref": "sk-raw-secret",
            },
        )
    assert invalid_ref.value.path == "$.input_ref"

    with pytest.raises(EventSchemaValidationError) as nested_bypass:
        catalog.validate(
            "phase_recorded",
            "newsroom.harness-event/v1",
            {
                "projection_schema": "harness-safe-summary/v1",
                "phase": "verify",
                "boundary": "exit",
                "input_ref_checksums": [],
                "output_ref_checksums": [],
                "gate_results": [
                    {
                        "gate": "quality",
                        "passed": False,
                        "operator_note": "sk-nested-policy-bypass",
                    }
                ],
                "metadata": {},
            },
        )
    assert nested_bypass.value.path == "$.gate_results[0]"


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
    phase_policy = catalog.get(
        "phase_recorded",
        "newsroom.harness-event/v1",
    ).sensitivity_policy
    step_state_policy = catalog.get(
        "step_state_changed",
        "newsroom.harness-event/v1",
    ).sensitivity_policy

    assert stream_policy.disposition_for("/stream_event") is FieldDisposition.REFERENCE_ONLY
    assert (
        stream_policy.whole_document_reference
        is WholeDocumentReferenceDisposition.SECURE_REQUIRED
    )
    assert worker_policy.disposition_for("/inputs") is FieldDisposition.REFERENCE_ONLY
    assert worker_policy.disposition_for("/metadata") is FieldDisposition.REFERENCE_ONLY
    assert (
        worker_policy.whole_document_reference
        is WholeDocumentReferenceDisposition.SECURE_REQUIRED
    )
    assert (
        phase_policy.whole_document_reference
        is WholeDocumentReferenceDisposition.SECURE_REQUIRED
    )
    assert (
        step_state_policy.whole_document_reference
        is WholeDocumentReferenceDisposition.SECURE_REQUIRED
    )

    decision_policy = catalog.get(
        "decision_recorded",
        "newsroom.harness-event/v1",
    ).sensitivity_policy
    phase_policy = catalog.get(
        "phase_recorded",
        "newsroom.harness-event/v1",
    ).sensitivity_policy
    assert decision_policy.disposition_for("/payload") is FieldDisposition.REFERENCE_ONLY
    assert decision_policy.disposition_for("/reason") is FieldDisposition.SENSITIVE
    assert (
        phase_policy.disposition_for("/gate_results/0/diagnostics")
        is FieldDisposition.REFERENCE_ONLY
    )


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


def test_schema_callable_reflection_and_io_exploits_have_zero_side_effect(
    tmp_path: Path,
) -> None:
    escaped = tmp_path / "schema-escape.txt"

    def helper() -> None:
        return None

    def reflection_upcaster(payload: object) -> dict[str, object]:
        builtins = helper.__globals__["__builtins__"]
        opener = builtins["open"]
        with opener(payload["path"], "a", encoding="utf-8") as stream:  # type: ignore[index]
            stream.write("escaped\n")
        return dict(payload)

    def direct_open_upcaster(payload: object) -> dict[str, object]:
        with open(payload["path"], "a", encoding="utf-8") as stream:  # type: ignore[index]
            stream.write("opened\n")
        return dict(payload)

    for upcaster in (reflection_upcaster, direct_open_upcaster):
        with pytest.raises(EventSchemaError, match="forbidden"):
            EventSchemaRegistration(
                event_type="io.newsroom.test",
                data_schema="io.newsroom.test/v1",
                json_schema={"type": "object"},
                upcast_to="io.newsroom.test/v2",
                upcaster=upcaster,
            )
    assert not escaped.exists()

    def reflection_validator(payload: object) -> None:
        builtins = helper.__globals__["__builtins__"]
        builtins["open"](payload["path"], "a").close()  # type: ignore[index]

    with pytest.raises(EventSchemaError, match="forbidden"):
        EventSchemaRegistration(
            event_type="io.newsroom.validator",
            data_schema="io.newsroom.validator/v1",
            json_schema={"type": "object"},
            custom_validator=reflection_validator,
            current=True,
        )
    assert not escaped.exists()


def test_schema_callable_rejects_import_getattr_and_unordered_containers() -> None:
    def importing(payload: object) -> dict[str, object]:
        import os as imported_os

        return {"payload": payload, "cwd": imported_os.getcwd()}

    def reflecting(payload: object) -> dict[str, object]:
        return {"value": getattr(payload, "items")}

    def frozenset_order(payload: object) -> dict[str, object]:
        return {"items": list(frozenset(payload["items"]))}  # type: ignore[index]

    def set_order(payload: object) -> dict[str, object]:
        return {"items": list({*payload["items"]})}  # type: ignore[index]

    for upcaster in (importing, reflecting, frozenset_order, set_order):
        with pytest.raises(EventSchemaError, match="forbidden"):
            EventSchemaRegistration(
                event_type="io.newsroom.test",
                data_schema="io.newsroom.test/v1",
                json_schema={"type": "object"},
                upcast_to="io.newsroom.test/v2",
                upcaster=upcaster,
            )


def test_schema_unordered_callable_is_rejected_across_python_hash_seeds() -> None:
    script = """
from framework.events.errors import EventSchemaError
from framework.events.schema import EventSchemaRegistration

def upcast(payload):
    return {"items": list(frozenset(payload["items"]))}

try:
    EventSchemaRegistration(
        event_type="io.newsroom.test",
        data_schema="io.newsroom.test/v1",
        json_schema={"type": "object"},
        upcast_to="io.newsroom.test/v2",
        upcaster=upcast,
    )
except EventSchemaError as exc:
    print(type(exc).__name__ + ":" + str(exc))
else:
    print("accepted")
"""
    outputs: list[str] = []
    for seed in ("1", "2", "3"):
        environment = dict(os.environ)
        environment["PYTHONHASHSEED"] = seed
        completed = subprocess.run(
            [sys.executable, "-c", script],
            cwd=ROOT,
            env=environment,
            check=True,
            capture_output=True,
            text=True,
        )
        outputs.append(completed.stdout.strip())

    assert outputs == [
        "EventSchemaError:event schema callable uses forbidden builtin: frozenset"
    ] * 3


def test_custom_validator_is_pure_single_argument_and_runs_once_per_validation() -> None:
    def validate_count(payload: object) -> None:
        if payload["count"] < 0:  # type: ignore[index]
            raise ValueError("count must be non-negative")

    catalog = EventSchemaCatalog()
    catalog.register(
        EventSchemaRegistration(
            event_type="io.newsroom.validator",
            data_schema="io.newsroom.validator/v1",
            json_schema={
                "type": "object",
                "required": ["count"],
                "properties": {"count": {"type": "integer"}},
            },
            custom_validator=validate_count,
            current=True,
        )
    )
    call_count = 0

    def trace_calls(frame: object, event: str, arg: object) -> object:
        nonlocal call_count
        if (
            event == "call"
            and frame.f_code is validate_count.__code__  # type: ignore[attr-defined]
        ):
            call_count += 1
        return trace_calls

    sys.settrace(trace_calls)
    try:
        assert catalog.validate(
            "io.newsroom.validator",
            "io.newsroom.validator/v1",
            {"count": 1},
        ) == {"count": 1}
        with pytest.raises(EventSchemaValidationError) as caught:
            catalog.validate(
                "io.newsroom.validator",
                "io.newsroom.validator/v1",
                {"count": -1},
            )
    finally:
        sys.settrace(None)

    assert caught.value.rule == "custom"
    assert call_count == 2


def test_custom_validator_rejects_non_none_result_as_typed_schema_error() -> None:
    def returns_payload(payload: object) -> object:
        return dict(payload)  # type: ignore[arg-type]

    catalog = EventSchemaCatalog()
    catalog.register(
        EventSchemaRegistration(
            event_type="io.newsroom.validator-result",
            data_schema="io.newsroom.validator-result/v1",
            json_schema={"type": "object"},
            custom_validator=returns_payload,  # type: ignore[arg-type]
            current=True,
        )
    )

    with pytest.raises(EventSchemaValidationError) as caught:
        catalog.validate(
            "io.newsroom.validator-result",
            "io.newsroom.validator-result/v1",
            {},
        )

    assert caught.value.rule == "custom"
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None


def test_pure_validator_runner_rejects_awaitable_result() -> None:
    async def deferred_result() -> None:
        return None

    awaitable = deferred_result()

    def returns_awaitable(payload: object) -> object:
        return awaitable

    try:
        with pytest.raises(TypeError, match="must return None"):
            _run_pure_validator(returns_awaitable, {})  # type: ignore[arg-type]
    finally:
        awaitable.close()


def test_upcaster_executes_once_after_purity_acceptance() -> None:
    def identity_upcaster(payload: object) -> dict[str, object]:
        return dict(payload)

    catalog = EventSchemaCatalog()
    catalog.register(
        EventSchemaRegistration(
            event_type="io.newsroom.once",
            data_schema="io.newsroom.once/v1",
            json_schema={"type": "object"},
            upcast_to="io.newsroom.once/v2",
            upcaster=identity_upcaster,
        )
    )
    catalog.register(
        EventSchemaRegistration(
            event_type="io.newsroom.once",
            data_schema="io.newsroom.once/v2",
            json_schema={"type": "object"},
            current=True,
        )
    )
    call_count = 0

    def trace_calls(frame: object, event: str, arg: object) -> object:
        nonlocal call_count
        if (
            event == "call"
            and frame.f_code is identity_upcaster.__code__  # type: ignore[attr-defined]
        ):
            call_count += 1
        return trace_calls

    sys.settrace(trace_calls)
    try:
        assert catalog.upcast("io.newsroom.once", "io.newsroom.once/v1", {})[0] == (
            "io.newsroom.once/v2"
        )
    finally:
        sys.settrace(None)

    assert call_count == 1


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
        return {"value": payload["missing_required_key"]}  # type: ignore[index]

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
