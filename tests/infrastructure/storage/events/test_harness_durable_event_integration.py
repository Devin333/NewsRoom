from __future__ import annotations

from framework.events.runtime.models import StreamReadRequest
from framework.events.runtime.publisher import EventRuntime
from framework.events.schema import default_event_schema_catalog
from framework.harness import (
    DurableHarnessEventPort,
    HarnessControlPlane,
    HarnessRunSpec,
    HarnessStepSpec,
    HarnessWorkerResult,
    HarnessWorkflowSpec,
)
from framework.shared.json import stable_json_dumps
from infrastructure.storage.events.sqlite import SQLiteEventStore


def test_harness_run_commits_through_default_catalog_and_sqlite_without_raw_worker_data(
    tmp_path,
) -> None:
    secret = "sk-harness-sqlite-integration-secret"
    store = SQLiteEventStore(tmp_path / "events.sqlite3")
    runtime = EventRuntime(
        store=store,
        schema_catalog=default_event_schema_catalog(),
    )
    event_port = DurableHarnessEventPort(runtime)
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
        StreamReadRequest(stream_id="run:run-real-sqlite", limit=100)
    )
    assert page.events
    assert [event.stream_sequence for event in page.events] == list(
        range(1, len(page.events) + 1)
    )
    assert secret not in stable_json_dumps([event.to_dict() for event in page.events])
