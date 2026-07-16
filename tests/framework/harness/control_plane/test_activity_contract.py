from __future__ import annotations

from datetime import UTC, datetime

import pytest

from framework.events import PayloadReference, checksum_for
from framework.events.errors import (
    EventIncompleteHistoryError,
    EventStoreCorruptionError,
)
from framework.events.schema import (
    REQUIRED_SECURE_PAYLOAD_CAPABILITIES,
    SecurePayloadValidation,
    SecurityClassification,
)
from framework.harness.control_plane.activity import (
    HARNESS_ACTIVITY_RESULT_SCHEMA,
    HarnessActivity,
    HarnessActivityResultRecord,
    resolve_activity_result,
)
from framework.harness.workers.result import HarnessWorkerResult
from framework.shared.json import stable_json_dumps


NOW = datetime(2026, 7, 16, 9, 0, tzinfo=UTC)


class _SecureActivityStore:
    def __init__(self) -> None:
        self._records: dict[str, dict] = {}
        self._tenants: dict[str, str] = {}
        self.resolve_calls = 0

    def put_result(self, record, *, tenant_id, classification):
        uri = f"secure-activity://{tenant_id}/{record.activity.activity_id}"
        payload = record.to_dict()
        existing = self._records.get(uri)
        if existing is not None and stable_json_dumps(existing) != stable_json_dumps(payload):
            raise EventStoreCorruptionError("activity identity collision")
        self._records[uri] = payload
        self._tenants[uri] = tenant_id
        return PayloadReference(
            uri=uri,
            expected_checksum=record.content_checksum,
            content_type="application/vnd.newsroom.harness-activity-result+json",
            size_bytes=len(stable_json_dumps(payload).encode("utf-8")),
        )

    def resolve_result(self, reference, *, tenant_id, classification):
        del classification
        self.resolve_calls += 1
        if not reference.uri.startswith(f"secure-activity://{tenant_id}/"):
            raise LookupError("not found")
        payload = self._records[reference.uri]
        return HarnessActivityResultRecord.from_dict(payload)

    def validate_reference(self, reference, *, tenant_id, classification):
        owner = self._tenants.get(reference["uri"])
        if owner is not None and owner != tenant_id:
            raise PermissionError("tenant is not authorized")
        return SecurePayloadValidation.for_reference(
            reference,
            tenant_id=tenant_id,
            classification=classification,
            capabilities=REQUIRED_SECURE_PAYLOAD_CAPABILITIES,
        )


def _activity(inputs=None) -> HarnessActivity:
    return HarnessActivity.for_worker_call(
        run_id="run-activity",
        step_id="collect",
        attempt=1,
        activity_type="llm",
        inputs=inputs or {"query": "safe"},
    )


def test_activity_identity_is_stable_and_input_content_is_integrity_bound() -> None:
    first = _activity({"query": "first"})
    retry = _activity({"query": "first"})
    conflict = _activity({"query": "changed"})

    assert retry.activity_id == first.activity_id
    assert retry.result_event_id == first.result_event_id
    assert retry.input_checksum == first.input_checksum
    assert conflict.activity_id == first.activity_id
    assert conflict.input_checksum != first.input_checksum


def test_activity_identity_is_tenant_scoped_without_persisting_raw_tenant() -> None:
    tenant_a_scope = checksum_for("tenant-a")
    tenant_b_scope = checksum_for("tenant-b")
    tenant_a = HarnessActivity.for_worker_call(
        run_id="shared-run",
        step_id="collect",
        attempt=1,
        activity_type="llm",
        inputs={"query": "same"},
        identity_scope_ref=tenant_a_scope,
    )
    tenant_b = HarnessActivity.for_worker_call(
        run_id="shared-run",
        step_id="collect",
        attempt=1,
        activity_type="llm",
        inputs={"query": "same"},
        identity_scope_ref=tenant_b_scope,
    )

    assert tenant_a.activity_id.startswith("harness-activity-v2:")
    assert tenant_a.result_event_id.startswith("harness-event-v2:")
    assert tenant_a.activity_id != tenant_b.activity_id
    assert tenant_a.result_event_id != tenant_b.result_event_id
    assert tenant_a.idempotency_key != tenant_b.idempotency_key
    assert "tenant-a" not in stable_json_dumps(tenant_a.to_dict())


def test_activity_result_takes_a_deeply_immutable_canonical_snapshot() -> None:
    output = {"nested": {"answer": "accepted"}}
    result = HarnessWorkerResult(status="succeeded", output=output)
    record = HarnessActivityResultRecord(
        activity=_activity(),
        result=result,
        completed_at=NOW,
    )
    checksum = record.content_checksum

    output["nested"]["answer"] = "mutated"
    result.output["nested"]["answer"] = "also-mutated"

    assert record.to_dict()["result"]["output"]["nested"]["answer"] == "accepted"
    assert record.content_checksum == checksum
    assert record.to_worker_result().output["nested"]["answer"] == "accepted"


def test_secure_activity_reference_resolves_and_verifies_exact_identity() -> None:
    store = _SecureActivityStore()
    activity = _activity()
    record = HarnessActivityResultRecord(
        activity=activity,
        result=HarnessWorkerResult(status="succeeded", output={"answer": "ready"}),
        completed_at=NOW,
    )
    reference = store.put_result(
        record,
        tenant_id="tenant-a",
        classification=SecurityClassification.CONFIDENTIAL,
    )

    resolved = resolve_activity_result(
        store,
        reference,
        expected_activity=activity,
        tenant_id="tenant-a",
        classification=SecurityClassification.CONFIDENTIAL,
    )

    assert resolved.schema == HARNESS_ACTIVITY_RESULT_SCHEMA
    assert resolved.to_worker_result().output == {"answer": "ready"}


def test_secure_activity_resolution_rejects_checksum_or_identity_corruption() -> None:
    store = _SecureActivityStore()
    activity = _activity()
    record = HarnessActivityResultRecord(
        activity=activity,
        result=HarnessWorkerResult(status="succeeded", output={"answer": "ready"}),
        completed_at=NOW,
    )
    reference = store.put_result(
        record,
        tenant_id="tenant-a",
        classification=SecurityClassification.CONFIDENTIAL,
    )
    store._records[reference.uri]["result"]["output"]["answer"] = "tampered"

    with pytest.raises(EventStoreCorruptionError, match="checksum"):
        resolve_activity_result(
            store,
            reference,
            expected_activity=activity,
            tenant_id="tenant-a",
            classification=SecurityClassification.CONFIDENTIAL,
        )


def test_secure_activity_resolution_fails_closed_when_result_is_missing() -> None:
    store = _SecureActivityStore()
    activity = _activity()
    record = HarnessActivityResultRecord(
        activity=activity,
        result=HarnessWorkerResult(status="succeeded", output={"answer": "ready"}),
        completed_at=NOW,
    )
    reference = store.put_result(
        record,
        tenant_id="tenant-a",
        classification=SecurityClassification.CONFIDENTIAL,
    )
    del store._records[reference.uri]

    with pytest.raises(EventIncompleteHistoryError, match="unavailable"):
        resolve_activity_result(
            store,
            reference,
            expected_activity=activity,
            tenant_id="tenant-a",
            classification=SecurityClassification.CONFIDENTIAL,
        )


def test_secure_activity_resolution_rejects_malformed_result_as_corruption() -> None:
    store = _SecureActivityStore()
    activity = _activity()
    record = HarnessActivityResultRecord(
        activity=activity,
        result=HarnessWorkerResult(status="succeeded", output={"answer": "ready"}),
        completed_at=NOW,
    )
    reference = store.put_result(
        record,
        tenant_id="tenant-a",
        classification=SecurityClassification.CONFIDENTIAL,
    )
    store._records[reference.uri]["completed_at"] = "not-a-timestamp"

    with pytest.raises(EventStoreCorruptionError, match="contract is invalid"):
        resolve_activity_result(
            store,
            reference,
            expected_activity=activity,
            tenant_id="tenant-a",
            classification=SecurityClassification.CONFIDENTIAL,
        )


def test_secure_activity_resolution_rejects_wrong_tenant_before_resolve() -> None:
    store = _SecureActivityStore()
    activity = _activity()
    record = HarnessActivityResultRecord(
        activity=activity,
        result=HarnessWorkerResult(status="succeeded", output={"answer": "ready"}),
        completed_at=NOW,
    )
    reference = store.put_result(
        record,
        tenant_id="tenant-a",
        classification=SecurityClassification.CONFIDENTIAL,
    )

    with pytest.raises(EventIncompleteHistoryError, match="unauthorized"):
        resolve_activity_result(
            store,
            reference,
            expected_activity=activity,
            tenant_id="tenant-b",
            classification=SecurityClassification.CONFIDENTIAL,
        )

    assert store.resolve_calls == 0
