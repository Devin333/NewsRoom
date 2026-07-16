from __future__ import annotations

import json
from datetime import UTC, datetime

from framework.events.canonical import BusinessContext, EventCandidate, ProducerIdentity
from framework.workflow.runtime.event_projection import WorkflowEventProjectionExporter
from infrastructure.storage.events.factory import durable_event_storage_from_env
from interfaces.services.run_inspection_factory import (
    RunInspectionEventAuthorizer,
    run_inspection_service_from_env,
)
from interfaces.services.event_reader_service import (
    EventAuthorizationContext,
    EventAuthorizationRequest,
    EventPermission,
)


def test_run_inspection_factory_reads_same_env_selected_durable_store(tmp_path) -> None:
    env = {
        "NEWS_ARTIFACT_ROOT": str(tmp_path),
        "NEWS_TENANT_ID": "tenant-a",
    }
    storage = durable_event_storage_from_env(env=env)
    stored = storage.event_store.append_event(_event())
    run_dir = tmp_path / "run-factory"
    run_dir.mkdir()
    projection = WorkflowEventProjectionExporter(
        reader=storage.event_store,
        schema_catalog=storage.schema_catalog,
    ).export(
        stream_id="run:run-factory",
        tenant_id="tenant-a",
        target=run_dir / "events.jsonl",
        through_sequence=stored.event.stream_sequence,
    )
    (run_dir / "manifest.json").write_text(
        json.dumps(
            {
                "run_id": "run-factory",
                "status": "succeeded",
                "artifacts": {"events": "events.jsonl"},
                "event_projection": {
                    "path": "events.jsonl",
                    "stream_id": projection.stream_id,
                    "high_watermark": projection.high_watermark,
                    "event_count": projection.event_count,
                    "checksum": projection.checksum,
                },
            }
        ),
        encoding="utf-8",
    )

    result = run_inspection_service_from_env(env=env).get_run_events("run-factory")

    assert result.source == "durable_store"
    assert result.availability == "available"
    assert result.projection_status == "current"
    assert result.events[0]["event_id"] == "evt-run-factory"


def test_run_inspection_factory_defers_event_store_for_artifact_reads(
    tmp_path,
    monkeypatch,
) -> None:
    import infrastructure.storage.events.factory as storage_factory

    run_dir = tmp_path / "run-artifact-only"
    run_dir.mkdir()
    (run_dir / "manifest.json").write_text(
        json.dumps({"run_id": "run-artifact-only", "status": "succeeded"}),
        encoding="utf-8",
    )

    def fail_if_composed(**kwargs):
        raise AssertionError("artifact inspection must not compose event storage")

    monkeypatch.setattr(
        storage_factory,
        "durable_event_storage_from_env",
        fail_if_composed,
    )

    service = run_inspection_service_from_env(
        env={"NEWS_ARTIFACT_ROOT": str(tmp_path)}
    )

    assert service.get_run("run-artifact-only").run_id == "run-artifact-only"


def test_run_inspection_authorizer_only_allows_exact_read_scope() -> None:
    authorization = EventAuthorizationContext(
        principal_id="inspection",
        tenant_id="tenant-a",
        authentication_evidence_ref="authn://service/inspection",
    )
    authorizer = RunInspectionEventAuthorizer(authorization)
    read_request = EventAuthorizationRequest(
        principal_id="inspection",
        tenant_id="tenant-a",
        authentication_evidence_ref="authn://service/inspection",
        operation=EventPermission.READ,
        target={"stream_id": "run:run-factory"},
    )
    mutation_request = EventAuthorizationRequest(
        principal_id="inspection",
        tenant_id="tenant-a",
        authentication_evidence_ref="authn://service/inspection",
        operation=EventPermission.PROJECTION_REBUILD,
        target={"stream_id": "run:run-factory"},
    )

    assert authorizer.authorize(read_request).authorized is True
    assert authorizer.authorize(mutation_request).authorized is False


def _event() -> EventCandidate:
    return EventCandidate(
        event_id="evt-run-factory",
        event_type="workflow_started",
        data_schema="newsroom.workflow-event/v1",
        source="io.newsroom.workflow.runtime",
        occurred_at=datetime(2026, 7, 16, 1, tzinfo=UTC),
        stream_id="run:run-factory",
        business_context=BusinessContext(
            run_id="run-factory",
            workflow_id="workflow-1",
        ),
        producer=ProducerIdentity(component="framework.workflow.runtime"),
        tenant_id="tenant-a",
        payload={"workflow_version": "1", "profile": "test"},
    )
