from __future__ import annotations

import ast
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from backend.foundation.models.source import RawSourceItem
from backend.foundation.primitives.source_ref import source_url_read_aliases
from backend.layers.signal.artifact_refs import SignalArtifactRef
from backend.layers.signal.artifacts import SourceArtifactWriter
from backend.layers.signal.source_processing.normalize import normalize_item
from framework.agent.artifacts import ArtifactManager
from framework.events.canonical import StoredEvent
from framework.events.runtime.replay_engine import ReplayCheckpoint
from infrastructure.storage.persistence import (
    LocalJsonPersistenceAdapter,
    RunPersistenceInput,
    persist_run_input,
    source_item_records_from_input,
)
from infrastructure.storage.records import SourceItemRecord


PROJECT_ROOT = Path(__file__).resolve().parents[2]
FIXTURE_ROOT = PROJECT_ROOT / "tests" / "fixtures" / "source_policy_persistence"
HISTORICAL_URL = "https://example.com/News/?topic=AI"
GOLDEN_URL = "https://example.com/News?topic=AI"
FIXED_TIME = datetime(2026, 7, 19, 8, 30, tzinfo=UTC)


def test_persisted_source_record_preserves_historical_identity_without_rewrite() -> None:
    fixture_path = FIXTURE_ROOT / "legacy_source_record.json"
    before_read = fixture_path.read_bytes()
    payload = _load_json(fixture_path)

    record = SourceItemRecord.from_dict(payload)
    aliases = source_url_read_aliases(record.canonical_url or record.url)

    assert record.source_item_id == "legacy-source-item"
    assert record.url == HISTORICAL_URL
    assert record.canonical_url == HISTORICAL_URL
    assert record.metadata["canonical_url_hash"] == "legacy-url-hash"
    assert aliases[0] == HISTORICAL_URL
    assert GOLDEN_URL in aliases
    assert record.to_dict() == payload
    assert fixture_path.read_bytes() == before_read


def test_source_artifact_index_and_payload_preserve_historical_url() -> None:
    index_path = FIXTURE_ROOT / "source_artifacts" / "index.json"
    item_path = (
        FIXTURE_ROOT
        / "sources"
        / "items"
        / "legacy-source"
        / "legacy-source-item.json"
    )
    before_read = {path: path.read_bytes() for path in (index_path, item_path)}
    index = _load_json(index_path)
    item_entry = next(
        entry for entry in index["entries"] if entry["artifact_type"] == "source_item"
    )
    item_ref = SignalArtifactRef.from_dict(item_entry["artifact_ref"])
    artifact_payload = _load_json(FIXTURE_ROOT / item_ref.path)
    item_payload = artifact_payload["item"]
    record = SourceItemRecord.from_dict(item_payload)

    assert item_ref.run_id == "legacy-source-run"
    assert item_ref.path == "sources/items/legacy-source/legacy-source-item.json"
    assert record.url == HISTORICAL_URL
    assert record.canonical_url == HISTORICAL_URL
    assert record.metadata["canonical_url_hash"] == "legacy-url-hash"
    assert GOLDEN_URL in source_url_read_aliases(record.canonical_url)
    assert {path: path.read_bytes() for path in before_read} == before_read


def test_source_event_and_replay_checkpoint_round_trip_historical_identity() -> None:
    event_path = FIXTURE_ROOT / "legacy_source_item_event.json"
    checkpoint_path = FIXTURE_ROOT / "legacy_source_item_replay_checkpoint.json"
    before_read = {path: path.read_bytes() for path in (event_path, checkpoint_path)}
    event_payload = _load_json(event_path)
    checkpoint_payload = _load_json(checkpoint_path)
    restored_event = StoredEvent.from_dict(event_payload)
    restored_checkpoint = ReplayCheckpoint.from_dict(checkpoint_payload)

    assert restored_event.to_dict() == event_payload
    assert restored_event.to_dict()["payload"]["canonical_url"] == HISTORICAL_URL
    assert restored_checkpoint.to_dict() == checkpoint_payload
    assert restored_checkpoint.to_dict()["state"]["source_items"][0]["canonical_url"] == HISTORICAL_URL
    assert GOLDEN_URL in source_url_read_aliases(HISTORICAL_URL)
    assert {path: path.read_bytes() for path in before_read} == before_read


def test_new_normalized_source_item_single_writes_golden_identity() -> None:
    raw = RawSourceItem(
        source_item_id="source-item-new",
        source_id="source-new",
        source_name="New Source",
        source_type="rss",
        title="New source item",
        url="HTTPS://Example.com/News/?UTM_Source=x&Topic=AI#section",
        fetched_at=FIXED_TIME,
    )

    normalized = normalize_item(raw)

    assert raw.url == "HTTPS://Example.com/News/?UTM_Source=x&Topic=AI#section"
    assert normalized.canonical_url == "https://example.com/News?Topic=AI"
    assert normalized.lineage.raw_url == raw.url
    assert normalized.lineage.canonical_url == normalized.canonical_url
    assert normalized.metadata["lineage"]["canonical_url"] == normalized.canonical_url
    assert "canonical_url_aliases" not in normalized.metadata
    assert "canonical_url_aliases" not in normalized.lineage.to_dict()


def test_source_artifact_writer_single_writes_only_golden_identity(
    tmp_path: Path,
) -> None:
    raw = RawSourceItem(
        source_item_id="source-item-new",
        source_id="source-new",
        source_name="New Source",
        source_type="rss",
        title="New source item",
        url="HTTPS://Example.com/News/?UTM_Source=x&topic=AI#section",
        fetched_at=FIXED_TIME,
    )
    normalized = normalize_item(raw)
    manager = ArtifactManager(tmp_path)
    manager.start_run("new-source-run")

    index = SourceArtifactWriter(manager).write_source_artifacts(
        "new-source-run",
        raw_items=[
            {
                "source_item_id": normalized.source_item_id,
                "source_id": normalized.source_id,
                "source_name": raw.source_name,
                "source_type": "rss",
                "title": normalized.title,
                "url": normalized.canonical_url,
                "canonical_url": normalized.canonical_url,
                "fetched_at": "2026-07-19T08:30:00Z",
                "lineage": normalized.lineage.to_dict(),
                "metadata": normalized.metadata,
            }
        ],
    )

    assert index is not None
    item_entries = [
        entry for entry in index["entries"] if entry["artifact_type"] == "source_item"
    ]
    assert len(item_entries) == 1
    run_dir = tmp_path / "new-source-run"
    assert len(list((run_dir / "sources" / "items").rglob("*.json"))) == 1
    persisted_index = _load_json(run_dir / "source_artifacts" / "index.json")
    emitted_payloads = [
        _load_json(run_dir / entry["path"])
        for entry in persisted_index["entries"]
        if entry["artifact_type"] in {"source_item", "source_parsed_items"}
    ]
    canonical_values = [
        value
        for payload in emitted_payloads
        for value in _values_for_key(payload, "canonical_url")
    ]

    assert canonical_values
    assert set(canonical_values) == {GOLDEN_URL}
    assert not any(
        _values_for_key(payload, "canonical_url_aliases")
        for payload in emitted_payloads
    )


def test_record_builder_and_local_writer_single_write_only_golden_identity(
    tmp_path: Path,
) -> None:
    raw = RawSourceItem(
        source_item_id="source-record-new",
        source_id="source-new",
        source_name="New Source",
        source_type="rss",
        title="New persisted source item",
        url="HTTPS://Example.com/News/?UTM_Source=x&topic=AI#section",
        fetched_at=FIXED_TIME,
    )
    normalized = normalize_item(raw)
    input_model = RunPersistenceInput(
        run_id="new-source-record-run",
        graph_id="source-policy-contract",
        graph_version="1",
        status="succeeded",
        profile="contract",
        raw_items=(
            {
                "source_item_id": normalized.source_item_id,
                "source_id": normalized.source_id,
                "title": normalized.title,
                "url": normalized.canonical_url,
                "canonical_url": normalized.canonical_url,
                "fetched_at": "2026-07-19T08:30:00Z",
                "content_hash": normalized.content_hash,
                "metadata": normalized.metadata,
            },
        ),
    )

    [record] = source_item_records_from_input(input_model)
    repository = LocalJsonPersistenceAdapter(tmp_path)
    persist_run_input(repository, input_model)

    record_paths = list(
        (tmp_path / "_records" / "source_items" / input_model.run_id).glob("*.json")
    )
    assert len(record_paths) == 1
    persisted_payload = _load_json(record_paths[0])
    persisted_record = SourceItemRecord.from_dict(persisted_payload)
    persistence_payloads = [
        _load_json(path) for path in (tmp_path / "_records").rglob("*.json")
    ]

    assert record.url == GOLDEN_URL
    assert record.canonical_url == GOLDEN_URL
    assert persisted_record.to_dict() == record.to_dict()
    assert persisted_record.url == GOLDEN_URL
    assert persisted_record.canonical_url == GOLDEN_URL
    assert not any(
        _values_for_key(payload, "canonical_url_aliases")
        for payload in persistence_payloads
    )
    assert {
        value
        for payload in persistence_payloads
        for value in _values_for_key(payload, "canonical_url")
    } == {GOLDEN_URL}


def test_infrastructure_url_adapter_has_no_algorithm_and_signal_copy_is_removed() -> None:
    adapter_path = PROJECT_ROOT / "infrastructure" / "external" / "sources" / "url_utils.py"
    tree = ast.parse(adapter_path.read_text(encoding="utf-8"), filename=str(adapter_path))
    imports = {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module is not None
    }

    assert imports == {"__future__", "backend.foundation.primitives.source_ref"}
    assert not any(isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) for node in ast.walk(tree))
    assert not (
        PROJECT_ROOT
        / "backend"
        / "layers"
        / "signal"
        / "source_processing"
        / "url_normalization.py"
    ).exists()


def _load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    return payload


def _values_for_key(value: Any, key: str) -> list[Any]:
    values: list[Any] = []
    if isinstance(value, dict):
        for nested_key, nested_value in value.items():
            if nested_key == key:
                values.append(nested_value)
            values.extend(_values_for_key(nested_value, key))
    elif isinstance(value, list):
        for nested_value in value:
            values.extend(_values_for_key(nested_value, key))
    return values
