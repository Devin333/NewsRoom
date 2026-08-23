from __future__ import annotations

import json

from infrastructure.storage.persistence.local_json_adapter import LocalJsonPersistenceAdapter
from infrastructure.storage.persistence.records import GraphRunRecord


def test_local_json_persistence_adapter_preserves_existing_record_format(tmp_path) -> None:
    adapter = LocalJsonPersistenceAdapter(tmp_path)

    adapter.save_graph_run(
        GraphRunRecord(
            run_id="run-1",
            graph_id="daily.graph",
            graph_version="1",
            status="succeeded",
            profile="live-offline",
        )
    )

    payload = json.loads((tmp_path / "_records" / "graph_runs" / "run-1.json").read_text())
    assert payload["run_id"] == "run-1"
    assert payload["graph_id"] == "daily.graph"
    assert payload["profile"] == "live-offline"
