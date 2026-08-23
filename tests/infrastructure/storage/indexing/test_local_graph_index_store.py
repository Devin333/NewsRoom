from __future__ import annotations

import json
from dataclasses import replace

import pytest

from infrastructure.storage.indexing import (
    GraphStorageIndexError,
    GraphStorageIndexErrorCode,
    GraphStorageIndexWriteStatus,
    LocalGraphStorageIndexStore,
)
from tests.infrastructure.storage.indexing.test_inactive_graph_index import (
    _adapter,
    _binding,
    _event,
    _events,
    _identity,
    _qualified_candidate,
    _manifest,
)


def test_live_store_writes_reads_and_queries_one_exact_identity(tmp_path) -> None:
    candidate = _qualified_candidate(tmp_path / "fixtures")
    store = LocalGraphStorageIndexStore(tmp_path / "index")

    first = store.write(candidate)
    second = store.write(candidate)
    restored = store.read(candidate.identity)

    assert first.status is GraphStorageIndexWriteStatus.WRITTEN
    assert second.status is GraphStorageIndexWriteStatus.IDEMPOTENT
    assert restored.candidate == candidate
    assert store.list_artifacts(candidate.identity)[0].artifact_id == "analysis-1"
    assert len(store.list_events(candidate.identity, node_instance_id="analyze:1")) == 1
    assert len(tuple((tmp_path / "index").glob("index-*.json"))) == 1


def test_live_store_rejects_same_identity_with_a_different_snapshot(tmp_path) -> None:
    candidate = _qualified_candidate(tmp_path / "fixtures")
    store = LocalGraphStorageIndexStore(tmp_path / "index")
    store.write(candidate)

    manifest = _manifest()
    changed = _adapter(tmp_path / "other-fixtures").dry_run(
        _request_with_events(
            manifest,
            (*_events(manifest), _event(3, _identity(manifest), with_node=True)),
        )
    ).candidate
    assert changed is not None

    with pytest.raises(GraphStorageIndexError) as raised:
        store.write(changed)

    assert raised.value.code is GraphStorageIndexErrorCode.INDEX_CONFLICT


def test_live_store_read_back_fails_closed_on_checksum_tamper(tmp_path) -> None:
    candidate = _qualified_candidate(tmp_path / "fixtures")
    store = LocalGraphStorageIndexStore(tmp_path / "index")
    store.write(candidate)
    target = next((tmp_path / "index").glob("index-*.json"))
    payload = json.loads(target.read_text(encoding="utf-8"))
    payload["candidate"]["event_records"][0]["event_type"] = "tampered"
    target.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(GraphStorageIndexError) as raised:
        store.read(candidate.identity)

    assert raised.value.code is GraphStorageIndexErrorCode.INDEX_CORRUPT


def test_live_store_rejects_identity_type_and_missing_snapshot(tmp_path) -> None:
    store = LocalGraphStorageIndexStore(tmp_path / "index")
    with pytest.raises(TypeError):
        store.read("not-an-identity")  # type: ignore[arg-type]

    candidate = _qualified_candidate(tmp_path / "fixtures")
    with pytest.raises(GraphStorageIndexError) as raised:
        store.read(
            replace(
                candidate.identity,
                terminal_manifest_hash="sha256:" + "0" * 64,
            )
        )

    assert raised.value.code is GraphStorageIndexErrorCode.INDEX_NOT_FOUND


def _request_with_events(manifest, events):
    from infrastructure.storage.indexing import GraphStorageIndexCandidateRequest

    return GraphStorageIndexCandidateRequest(
        manifest=manifest,
        events=events,
        artifact_bindings=(_binding(),),
    )
