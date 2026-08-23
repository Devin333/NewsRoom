"""Canonical Graph storage index publication service."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from framework.events.ports import EventReaderPort
from framework.harness.artifacts import GraphTerminalManifestV2
from infrastructure.storage.indexing.active import (
    GraphStorageIndexCandidateMaterializer,
)
from infrastructure.storage.indexing.contracts import (
    GraphStorageIndexError,
    GraphStorageIndexErrorCode,
)
from infrastructure.storage.indexing.local_store import (
    GraphStorageIndexSnapshot,
    GraphStorageIndexStorePort,
    GraphStorageIndexWriteReceipt,
)


@runtime_checkable
class GraphTerminalManifestReaderPort(Protocol):
    """Read the canonical terminal manifest for one Graph run."""

    def read_terminal_manifest(self, run_id: str) -> GraphTerminalManifestV2: ...


class GraphStorageIndexPublisher:
    """Materialize, persist, and read back one canonical Graph index."""

    def __init__(
        self,
        *,
        manifest_reader: GraphTerminalManifestReaderPort,
        event_reader: EventReaderPort,
        index_store: GraphStorageIndexStorePort,
        materializer: GraphStorageIndexCandidateMaterializer | None = None,
    ) -> None:
        if not isinstance(manifest_reader, GraphTerminalManifestReaderPort):
            raise TypeError(
                "manifest_reader must implement GraphTerminalManifestReaderPort"
            )
        if not isinstance(event_reader, EventReaderPort):
            raise TypeError("event_reader must implement EventReaderPort")
        if not isinstance(index_store, GraphStorageIndexStorePort):
            raise TypeError("index_store must implement GraphStorageIndexStorePort")
        if materializer is not None and not isinstance(
            materializer,
            GraphStorageIndexCandidateMaterializer,
        ):
            raise TypeError(
                "materializer must be GraphStorageIndexCandidateMaterializer"
            )
        self.manifest_reader = manifest_reader
        self.event_reader = event_reader
        self.index_store = index_store
        self.materializer = materializer or GraphStorageIndexCandidateMaterializer(
            event_reader=event_reader,
        )

    def publish(
        self,
        *,
        run_id: str,
        expected_manifest_hash: str,
    ) -> GraphStorageIndexWriteReceipt:
        if not isinstance(run_id, str) or not run_id.strip():
            raise GraphStorageIndexError(
                GraphStorageIndexErrorCode.REQUEST_INVALID,
                "Graph index publication run_id is required",
                field="run_id",
            )
        if (
            not isinstance(expected_manifest_hash, str)
            or not expected_manifest_hash.startswith("sha256:")
            or len(expected_manifest_hash) != 71
        ):
            raise GraphStorageIndexError(
                GraphStorageIndexErrorCode.REQUEST_INVALID,
                "Graph index publication manifest hash is invalid",
                field="expected_manifest_hash",
            )
        manifest = self.manifest_reader.read_terminal_manifest(run_id)
        if not isinstance(manifest, GraphTerminalManifestV2):
            raise GraphStorageIndexError(
                GraphStorageIndexErrorCode.REQUEST_INVALID,
                "Graph index publication requires a version-2 terminal manifest",
                field="manifest",
            )
        if manifest.run_id != run_id or manifest.manifest_hash != expected_manifest_hash:
            raise GraphStorageIndexError(
                GraphStorageIndexErrorCode.INDEX_CONFLICT,
                "Canonical Graph terminal manifest changed before index publication",
                field="manifest_hash",
            )

        candidate = self.materializer.materialize(manifest)
        receipt = self.index_store.write(candidate)
        if not isinstance(receipt, GraphStorageIndexWriteReceipt):
            raise GraphStorageIndexError(
                GraphStorageIndexErrorCode.INDEX_CORRUPT,
                "Graph storage index writer returned an invalid receipt",
                field="receipt",
            )
        snapshot = self.index_store.read(candidate.identity)
        if not isinstance(snapshot, GraphStorageIndexSnapshot):
            raise GraphStorageIndexError(
                GraphStorageIndexErrorCode.INDEX_CORRUPT,
                "Graph storage index reader returned an invalid snapshot",
                field="snapshot",
            )
        try:
            snapshot.verify_integrity()
        except (GraphStorageIndexError, TypeError, ValueError) as exc:
            raise GraphStorageIndexError(
                GraphStorageIndexErrorCode.INDEX_CORRUPT,
                "Graph storage index read-back failed integrity verification",
                field="snapshot",
            ) from exc
        if (
            snapshot.candidate != candidate
            or receipt.identity_ref != candidate.identity.identity_ref
            or receipt.snapshot_ref != snapshot.snapshot_ref
            or receipt.snapshot_checksum != snapshot.snapshot_checksum
        ):
            raise GraphStorageIndexError(
                GraphStorageIndexErrorCode.INDEX_CORRUPT,
                "Graph storage index read-back changed the published candidate",
                field="snapshot",
            )
        return receipt


__all__ = [
    "GraphStorageIndexPublisher",
    "GraphTerminalManifestReaderPort",
]
