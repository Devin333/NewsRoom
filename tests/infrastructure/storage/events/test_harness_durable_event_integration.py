from __future__ import annotations

import pytest

from framework.events import PayloadReference
from framework.events.errors import EventIncompleteHistoryError, EventStoreCorruptionError
from framework.events.runtime.models import StreamReadRequest
from framework.events.runtime.publisher import EventRuntime
from framework.events.schema import (
    REQUIRED_SECURE_PAYLOAD_CAPABILITIES,
    EventSecurityProjector,
    SecurePayloadValidation,
    SecurityClassification,
    default_event_schema_catalog,
)
from framework.harness import (
    DurableHarnessTransitionPort,
    HarnessEventCanonicalAdapter,
    HarnessControlPlane,
    HarnessRunSpec,
    HarnessStepSpec,
    HarnessWorkerResult,
    HarnessWorkflowSpec,
)
from framework.harness.control_plane.activity import HarnessActivityResultRecord
from framework.shared.json import stable_json_dumps
from infrastructure.storage.events.sqlite import SQLiteEventStore


class _SecureActivityStore:
    def __init__(self) -> None:
        self.records: dict[str, dict] = {}

    def put_result(self, record, *, tenant_id, classification):
        del classification
        uri = f"secure-activity://{tenant_id}/{record.activity.activity_id}"
        payload = record.to_dict()
        existing = self.records.get(uri)
        if existing is not None and stable_json_dumps(existing) != stable_json_dumps(payload):
            raise EventStoreCorruptionError("activity result identity collision")
        self.records[uri] = payload
        return PayloadReference(
            uri=uri,
            expected_checksum=record.content_checksum,
            content_type="application/vnd.newsroom.harness-activity-result+json",
            size_bytes=len(stable_json_dumps(payload).encode("utf-8")),
        )

    def resolve_result(self, reference, *, tenant_id, classification):
        del classification
        if not reference.uri.startswith(f"secure-activity://{tenant_id}/"):
            raise LookupError("not found")
        return HarnessActivityResultRecord.from_dict(self.records[reference.uri])

    def validate_reference(self, reference, *, tenant_id, classification):
        return SecurePayloadValidation.for_reference(
            reference,
            tenant_id=tenant_id,
            classification=classification,
            capabilities=REQUIRED_SECURE_PAYLOAD_CAPABILITIES,
        )


def test_harness_without_secure_activity_store_fails_before_worker(tmp_path) -> None:
    worker_calls = 0

    def worker(task):
        nonlocal worker_calls
        worker_calls += 1
        return HarnessWorkerResult(status="succeeded")

    store = SQLiteEventStore(tmp_path / "events.sqlite3")
    runtime = EventRuntime(
        store=store,
        schema_catalog=default_event_schema_catalog(),
    )
    event_port = DurableHarnessTransitionPort(runtime, store)
    workflow = HarnessWorkflowSpec(
        workflow_id="durable-integration",
        steps=(HarnessStepSpec(step_id="collect", worker_type="llm"),),
        entry_step_id="collect",
    )

    with pytest.raises(EventIncompleteHistoryError, match="secure activity result store"):
        HarnessControlPlane(
            event_port=event_port,
            worker_registry={"collect": worker},
        ).run(HarnessRunSpec(run_id="run-no-secure-store", workflow=workflow))

    assert worker_calls == 0


def test_harness_run_commits_through_default_catalog_and_sqlite_without_raw_worker_data(
    tmp_path,
) -> None:
    secret = "sk-harness-sqlite-integration-secret"
    secure_store = _SecureActivityStore()
    store = SQLiteEventStore(tmp_path / "events.sqlite3")
    runtime = EventRuntime(
        store=store,
        schema_catalog=default_event_schema_catalog(),
        security_projector=EventSecurityProjector(
            secure_payload_store=secure_store,
        ),
    )
    event_port = DurableHarnessTransitionPort(
        runtime,
        store,
        secure_activity_store=secure_store,
        adapter=HarnessEventCanonicalAdapter(
            tenant_id="tenant-test",
            security_classification=SecurityClassification.INTERNAL,
        ),
    )
    workflow = HarnessWorkflowSpec(
        workflow_id="durable-integration",
        steps=(HarnessStepSpec(step_id="collect", worker_type="llm"),),
        entry_step_id="collect",
    )

    result = HarnessControlPlane(
        event_port=event_port,
        worker_registry={
            "collect": lambda task: HarnessWorkerResult(
                status="succeeded",
                output={"answer": secret},
                diagnostics={"provider_message": secret},
            )
        },
    ).run(HarnessRunSpec(run_id="run-real-sqlite", workflow=workflow))

    assert result.succeeded is True
    page = store.read_stream(
        StreamReadRequest(
            stream_id="run:run-real-sqlite",
            limit=100,
            tenant_id="tenant-test",
        )
    )
    assert page.events
    assert [event.stream_sequence for event in page.events] == list(
        range(1, len(page.events) + 1)
    )
    assert secret not in stable_json_dumps([event.to_dict() for event in page.events])


def test_approval_restart_recovers_secure_worker_result_without_reinvocation(
    tmp_path,
) -> None:
    worker_calls = 0

    def worker(task):
        nonlocal worker_calls
        worker_calls += 1
        return HarnessWorkerResult(
            status="succeeded",
            output={"candidate": "ready"},
        )

    secure_store = _SecureActivityStore()
    store = SQLiteEventStore(tmp_path / "events.sqlite3")

    def build_port():
        runtime = EventRuntime(
            store=store,
            schema_catalog=default_event_schema_catalog(),
            security_projector=EventSecurityProjector(
                secure_payload_store=secure_store,
            ),
        )
        return DurableHarnessTransitionPort(
            runtime,
            store,
            secure_activity_store=secure_store,
            adapter=HarnessEventCanonicalAdapter(tenant_id="tenant-test"),
        )

    run_spec = HarnessRunSpec(
        run_id="run-approval-restart",
        workflow=HarnessWorkflowSpec(
            workflow_id="approval-restart",
            steps=(
                HarnessStepSpec(
                    step_id="collect",
                    worker_type="llm",
                    metadata={"approval_required": True},
                ),
            ),
            entry_step_id="collect",
            metadata={"version": "1"},
        ),
    )
    waiting = HarnessControlPlane(
        event_port=build_port(),
        worker_registry={"collect": worker},
    ).run(run_spec)
    assert waiting.state.status.value == "waiting_approval"

    resumed = HarnessControlPlane(
        event_port=build_port(),
        worker_registry={"collect": worker},
    ).resume_after_approval(run_spec, approved=True)

    assert resumed.state.status.value == "succeeded"
    assert worker_calls == 1
