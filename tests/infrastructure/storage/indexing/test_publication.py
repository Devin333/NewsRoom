from __future__ import annotations

import pytest

from framework.events.canonical import checksum_for
from infrastructure.storage.indexing import (
    GraphStorageIndexError,
    GraphStorageIndexErrorCode,
    GraphStorageIndexPublisher,
    GraphStorageIndexWriteStatus,
    LocalGraphStorageIndexStore,
)
from tests.infrastructure.storage.indexing.test_active_graph_index import (
    _Reader,
    _mixed_manifest,
)
from tests.infrastructure.storage.indexing.test_inactive_graph_index import _events


def test_publisher_rereads_canonical_manifest_and_verifies_snapshot(tmp_path) -> None:
    manifest = _mixed_manifest()
    reader = _Reader(_events(manifest))
    store = LocalGraphStorageIndexStore(tmp_path / "index")
    publisher = GraphStorageIndexPublisher(
        manifest_reader=_ManifestReader(manifest),
        event_reader=reader,
        index_store=store,
    )

    first = publisher.publish(
        run_id=manifest.run_id,
        expected_manifest_hash=manifest.manifest_hash,
    )
    second = publisher.publish(
        run_id=manifest.run_id,
        expected_manifest_hash=manifest.manifest_hash,
    )

    assert first.status is GraphStorageIndexWriteStatus.WRITTEN
    assert second.status is GraphStorageIndexWriteStatus.IDEMPOTENT
    assert first.snapshot_checksum == second.snapshot_checksum
    assert store.read(_identity_from_publisher(publisher)).snapshot_checksum == (
        first.snapshot_checksum
    )
    assert reader.requests
    assert all(request.through_sequence == 2 for request in reader.requests)


def test_publisher_rejects_changed_canonical_manifest(tmp_path) -> None:
    manifest = _mixed_manifest()
    publisher = GraphStorageIndexPublisher(
        manifest_reader=_ManifestReader(manifest),
        event_reader=_Reader(_events(manifest)),
        index_store=LocalGraphStorageIndexStore(tmp_path / "index"),
    )

    with pytest.raises(GraphStorageIndexError) as raised:
        publisher.publish(
            run_id=manifest.run_id,
            expected_manifest_hash=checksum_for({"manifest": "other"}),
        )

    assert raised.value.code is GraphStorageIndexErrorCode.INDEX_CONFLICT


def test_publisher_rejects_invalid_read_back(tmp_path) -> None:
    manifest = _mixed_manifest()
    store = _InvalidReadBackStore(tmp_path / "index")
    publisher = GraphStorageIndexPublisher(
        manifest_reader=_ManifestReader(manifest),
        event_reader=_Reader(_events(manifest)),
        index_store=store,
    )

    with pytest.raises(GraphStorageIndexError) as raised:
        publisher.publish(
            run_id=manifest.run_id,
            expected_manifest_hash=manifest.manifest_hash,
        )

    assert raised.value.code is GraphStorageIndexErrorCode.INDEX_CORRUPT


class _ManifestReader:
    def __init__(self, manifest) -> None:
        self.manifest = manifest
        self.calls: list[str] = []

    def read_terminal_manifest(self, run_id):
        self.calls.append(run_id)
        return self.manifest


class _InvalidReadBackStore:
    def __init__(self, root) -> None:
        self.delegate = LocalGraphStorageIndexStore(root)

    def write(self, candidate):
        return self.delegate.write(candidate)

    def read(self, identity):
        del identity
        return object()

    def list_artifacts(self, identity, *, node_instance_id=None):
        return self.delegate.list_artifacts(
            identity,
            node_instance_id=node_instance_id,
        )

    def list_events(self, identity, *, node_instance_id=None):
        return self.delegate.list_events(
            identity,
            node_instance_id=node_instance_id,
        )


def _identity_from_publisher(publisher):
    return publisher.materializer.materialize(
        publisher.manifest_reader.manifest,
    ).identity
