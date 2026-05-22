from __future__ import annotations

import json

from infrastructure.storage.persistence.local_json_adapter import LocalJsonPersistenceAdapter
from infrastructure.storage.persistence.records import WorkflowRunRecord


def test_local_json_persistence_adapter_preserves_existing_record_format(tmp_path) -> None:
    adapter = LocalJsonPersistenceAdapter(tmp_path)

    adapter.save_workflow_run(
        WorkflowRunRecord(
            run_id="run-1",
            workflow_id="daily",
            workflow_version="1",
            status="succeeded",
            profile="live-offline",
        )
    )

    payload = json.loads((tmp_path / "_records" / "workflow_runs" / "run-1.json").read_text())
    assert payload["run_id"] == "run-1"
    assert payload["workflow_id"] == "daily"
    assert payload["profile"] == "live-offline"
