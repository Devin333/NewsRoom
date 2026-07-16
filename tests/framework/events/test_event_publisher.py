from __future__ import annotations

from datetime import UTC, datetime

import pytest

from framework.events import (
    AppendResult,
    BusinessContext,
    EventCandidate,
    EventContextConflictError,
    EventPublishRequest,
    EventRuntime,
    EventSchemaCatalog,
    EventSchemaRegistration,
    EventSchemaValidationError,
    EventSecurePayloadRequiredError,
    EventSecurityError,
    PayloadReference,
    ProducerIdentity,
    SecurityClassification,
    SensitivityPolicy,
    StoredEvent,
)
from framework.events.schema import WholeDocumentReferenceDisposition


CHECKSUM = "sha256:" + "a" * 64
OCCURRED_AT = datetime(2026, 7, 15, 8, 0, tzinfo=UTC)
OBSERVED_AT = datetime(2026, 7, 15, 8, 0, 1, tzinfo=UTC)


class _UnitOfWork:
    def __init__(
        self,
        *,
        stored: StoredEvent | None = None,
        commit_error: Exception | None = None,
    ) -> None:
        self.stored = stored
        self.commit_error = commit_error
        self.appended: list[EventCandidate] = []
        self.expected_last_sequences: list[int | None] = []
        self.commits = 0
        self.rollbacks = 0

    def append_event(
        self,
        event: EventCandidate,
        *,
        expected_last_sequence: int | None = None,
    ) -> AppendResult:
        self.appended.append(event)
        self.expected_last_sequences.append(expected_last_sequence)
        stored = self.stored or StoredEvent(
            candidate=event,
            observed_at=OBSERVED_AT,
            stream_sequence=3,
        )
        return AppendResult(
            event=stored,
            created=self.stored is None,
            pending_delivery_count=0,
        )

    def settle_delivery(self, settlement):  # pragma: no cover - protocol-only method
        raise NotImplementedError

    def commit(self) -> None:
        self.commits += 1
        if self.commit_error is not None:
            raise self.commit_error

    def rollback(self) -> None:
        self.rollbacks += 1

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        if exc_type is not None or self.commits == 0:
            self.rollback()
        return False


class _Store:
    def __init__(self, unit_of_work: _UnitOfWork) -> None:
        self.value = unit_of_work
        self.unit_of_work_calls = 0

    def unit_of_work(self) -> _UnitOfWork:
        self.unit_of_work_calls += 1
        return self.value


def _catalog(
    *,
    policy: SensitivityPolicy | None = None,
) -> EventSchemaCatalog:
    catalog = EventSchemaCatalog()
    catalog.register(
        EventSchemaRegistration(
            event_type="io.newsroom.test.published",
            data_schema="io.newsroom.test.published/v1",
            json_schema={
                "type": "object",
                "properties": {
                    "message": {"type": "string"},
                    "token": {"type": "string"},
                },
                "required": ["message"],
                "additionalProperties": False,
            },
            sensitivity_policy=policy or SensitivityPolicy(),
            current=True,
        )
    )
    return catalog


def _request(**changes) -> EventPublishRequest:
    values = {
        "event_id": "evt-publish-1",
        "event_type": "io.newsroom.test.published",
        "data_schema": "io.newsroom.test.published/v1",
        "source": "tests.publisher",
        "occurred_at": OCCURRED_AT,
        "stream_id": "run:publish-1",
        "business_context": BusinessContext(run_id="publish-1"),
        "producer": ProducerIdentity(component="publisher-test", version="1"),
        "tenant_id": "tenant-a",
        "payload": {"message": "accepted"},
    }
    values.update(changes)
    return EventPublishRequest(**values)


def test_publish_validates_projects_appends_and_commits_before_return() -> None:
    source_payload = {"message": "accepted", "token": "must-not-persist"}
    request = _request(payload=source_payload)
    source_payload["message"] = "mutated-after-request"
    unit_of_work = _UnitOfWork()
    store = _Store(unit_of_work)
    runtime = EventRuntime(
        store=store,
        schema_catalog=_catalog(
            policy=SensitivityPolicy(
                field_rules={"/token": "sensitive"},
                redact_sensitive=True,
            )
        ),
    )

    stored = runtime.publish(request)

    assert store.unit_of_work_calls == 1
    assert unit_of_work.commits == 1
    assert unit_of_work.rollbacks == 0
    assert stored.stream_sequence == 3
    assert stored.observed_at == OBSERVED_AT
    assert stored.payload == {"message": "accepted", "token": "[REDACTED]"}
    assert "must-not-persist" not in str(stored.to_dict())
    assert unit_of_work.appended[0].content_checksum == stored.content_checksum


def test_validation_and_security_fail_before_store_or_sequence_allocation() -> None:
    unit_of_work = _UnitOfWork()
    store = _Store(unit_of_work)
    runtime = EventRuntime(store=store, schema_catalog=_catalog())

    with pytest.raises(EventSchemaValidationError):
        runtime.publish(_request(payload={"message": 42}))
    with pytest.raises(EventSecurityError):
        runtime.publish(_request(extensions={"stream_sequence": 999}))

    assert store.unit_of_work_calls == 0
    assert unit_of_work.appended == []


def test_publish_forwards_expected_stream_position_to_unit_of_work() -> None:
    unit_of_work = _UnitOfWork()
    runtime = EventRuntime(store=_Store(unit_of_work), schema_catalog=_catalog())

    stored = runtime.publish(_request(), expected_last_sequence=2)

    assert stored.stream_sequence == 3
    assert unit_of_work.expected_last_sequences == [2]


@pytest.mark.parametrize("value", [-1, True, 1.5])
def test_publish_rejects_invalid_expected_stream_position_before_store(value) -> None:
    unit_of_work = _UnitOfWork()
    runtime = EventRuntime(store=_Store(unit_of_work), schema_catalog=_catalog())

    with pytest.raises((TypeError, ValueError), match="expected_last_sequence"):
        runtime.publish(_request(), expected_last_sequence=value)

    assert unit_of_work.appended == []


def test_publish_strips_equal_context_duplicate_and_rejects_conflict_before_store() -> None:
    catalog = EventSchemaCatalog()
    catalog.register(
        EventSchemaRegistration(
            event_type="io.newsroom.test.context",
            data_schema="io.newsroom.test.context/v1",
            json_schema={
                "type": "object",
                "properties": {"message": {"type": "string"}},
                "required": ["message"],
                "additionalProperties": False,
            },
            authoritative_context_fields=("run_id",),
            current=True,
        )
    )
    unit_of_work = _UnitOfWork()
    store = _Store(unit_of_work)
    runtime = EventRuntime(store=store, schema_catalog=catalog)
    request_values = {
        "event_id": "evt-context-1",
        "event_type": "io.newsroom.test.context",
        "data_schema": "io.newsroom.test.context/v1",
        "source": "tests.publisher",
        "occurred_at": OCCURRED_AT,
        "stream_id": "run:publish-1",
        "business_context": BusinessContext(run_id="publish-1"),
        "producer": ProducerIdentity(component="publisher-test", version="1"),
    }

    accepted = runtime.publish(
        EventPublishRequest(
            **request_values,
            payload={"message": "accepted", "run_id": "publish-1"},
        )
    )

    assert accepted.payload == {"message": "accepted"}
    assert store.unit_of_work_calls == 1
    with pytest.raises(EventContextConflictError, match="run_id"):
        runtime.publish(
            EventPublishRequest(
                **{**request_values, "event_id": "evt-context-2"},
                payload={"message": "rejected", "run_id": "another-run"},
            )
        )
    assert store.unit_of_work_calls == 1


def test_caller_owned_unit_of_work_is_not_committed_by_runtime() -> None:
    owned = _UnitOfWork()
    runtime = EventRuntime(store=_Store(_UnitOfWork()), schema_catalog=_catalog())

    stored = runtime.publish(_request(), unit_of_work=owned)

    assert stored.stream_sequence == 3
    assert len(owned.appended) == 1
    assert owned.commits == 0
    assert owned.rollbacks == 0


def test_commit_failure_rolls_back_and_no_stored_event_is_returned() -> None:
    unit_of_work = _UnitOfWork(commit_error=RuntimeError("commit unavailable"))
    runtime = EventRuntime(store=_Store(unit_of_work), schema_catalog=_catalog())

    with pytest.raises(RuntimeError, match="commit unavailable"):
        runtime.publish(_request())

    assert unit_of_work.commits == 1
    assert unit_of_work.rollbacks == 1


def test_identical_duplicate_returns_original_store_assignment() -> None:
    first_candidate = EventCandidate(
        event_id="evt-publish-1",
        event_type="io.newsroom.test.published",
        data_schema="io.newsroom.test.published/v1",
        source="tests.publisher",
        occurred_at=OCCURRED_AT,
        stream_id="run:publish-1",
        business_context=BusinessContext(run_id="publish-1"),
        producer=ProducerIdentity(component="publisher-test", version="1"),
        tenant_id="tenant-a",
        payload={"message": "accepted"},
    )
    existing = StoredEvent(first_candidate, OBSERVED_AT, 17)
    unit_of_work = _UnitOfWork(stored=existing)
    runtime = EventRuntime(store=_Store(unit_of_work), schema_catalog=_catalog())

    duplicate = runtime.publish(_request())

    assert duplicate == existing
    assert duplicate.stream_sequence == 17
    assert unit_of_work.commits == 1


def test_payload_reference_requires_schema_opt_in_and_matching_content_type() -> None:
    reference = PayloadReference(
        uri="artifact://tenant-a/run/large.json",
        expected_checksum=CHECKSUM,
        content_type="application/json",
        size_bytes=100,
    )
    denied = EventRuntime(store=_Store(_UnitOfWork()), schema_catalog=_catalog())
    with pytest.raises(EventSecurityError, match="does not permit"):
        denied.publish(_request(payload=None, payload_ref=reference))

    permitted = EventRuntime(
        store=_Store(_UnitOfWork()),
        schema_catalog=_catalog(
            policy=SensitivityPolicy(
                whole_document_reference=(
                    WholeDocumentReferenceDisposition.NON_SENSITIVE
                ),
                max_inline_payload_bytes=8,
            )
        ),
    )
    stored = permitted.publish(_request(payload=None, payload_ref=reference))
    assert stored.payload is None
    assert stored.payload_ref == reference

    with pytest.raises(ValueError, match="content_type"):
        permitted.publish(
            _request(
                content_type="application/octet-stream",
                payload=None,
                payload_ref=reference,
            )
        )


def test_protected_content_fails_closed_before_store_without_secure_composition() -> None:
    unit_of_work = _UnitOfWork()
    runtime = EventRuntime(
        store=_Store(unit_of_work),
        schema_catalog=_catalog(
            policy=SensitivityPolicy(
                whole_document_reference=(
                    WholeDocumentReferenceDisposition.SECURE_REQUIRED
                ),
                max_inline_payload_bytes=8,
            )
        ),
    )
    reference = PayloadReference(
        uri="secure://tenant-a/run/content",
        expected_checksum=CHECKSUM,
        content_type="application/json",
        size_bytes=100,
    )

    with pytest.raises(EventSecurePayloadRequiredError):
        runtime.publish(
            _request(
                payload=None,
                payload_ref=reference,
                security_classification=SecurityClassification.CONFIDENTIAL,
            )
        )

    assert unit_of_work.appended == []
