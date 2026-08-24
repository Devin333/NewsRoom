"""Read-only authority for one checksum-bound Graph storage index snapshot."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Protocol, runtime_checkable

from framework.harness.artifacts.terminal_manifest import GraphTerminalManifestV2
from infrastructure.storage.indexing.bindings import GraphArtifactBindingProjection
from infrastructure.storage.indexing.contracts import (
    GraphArtifactIndexRecord,
    GraphStorageIndexError,
    GraphStorageIndexErrorCode,
    GraphStorageIndexIdentity,
)
from infrastructure.storage.indexing.local_store import (
    GraphStorageIndexSnapshot,
    GraphStorageIndexStorePort,
)
from infrastructure.storage.indexing.selection import (
    graph_indexable_terminal_artifacts,
)


@runtime_checkable
class GraphStorageIndexReaderPort(Protocol):
    """Application-facing read boundary for a canonical Graph index."""

    def read_for_manifest(
        self,
        manifest: GraphTerminalManifestV2,
    ) -> GraphStorageIndexSnapshot: ...


class GraphStorageIndexReader:
    """Resolve and verify exactly one index snapshot for a terminal manifest."""

    def __init__(self, store: GraphStorageIndexStorePort) -> None:
        if not isinstance(store, GraphStorageIndexStorePort):
            raise TypeError("store must implement GraphStorageIndexStorePort")
        self.store = store

    def read_for_manifest(
        self,
        manifest: GraphTerminalManifestV2,
    ) -> GraphStorageIndexSnapshot:
        if not isinstance(manifest, GraphTerminalManifestV2):
            raise TypeError("manifest must be GraphTerminalManifestV2")
        identity = GraphStorageIndexIdentity.from_manifest(manifest)
        try:
            snapshot = self.store.read(identity)
            snapshot.verify_integrity()
        except GraphStorageIndexError:
            raise
        except (TypeError, ValueError) as exc:
            raise GraphStorageIndexError(
                GraphStorageIndexErrorCode.INDEX_CORRUPT,
                "Graph storage index read-back is invalid",
                field="snapshot",
            ) from exc
        if snapshot.identity != identity:
            raise GraphStorageIndexError(
                GraphStorageIndexErrorCode.INDEX_SCOPE_MISMATCH,
                "Graph storage index read-back changed the manifest identity",
                field="identity",
            )
        _verify_manifest_artifact_records(manifest, snapshot)
        return snapshot


def _verify_manifest_artifact_records(
    manifest: GraphTerminalManifestV2,
    snapshot: GraphStorageIndexSnapshot,
) -> None:
    """Rebuild the expected artifact rows before granting reader authority."""

    try:
        artifacts = graph_indexable_terminal_artifacts(manifest)
    except (TypeError, ValueError) as exc:
        raise GraphStorageIndexError(
            GraphStorageIndexErrorCode.INDEX_CORRUPT,
            "Graph index manifest artifact selection is invalid",
            field="artifacts",
        ) from exc

    expected: dict[str, GraphArtifactIndexRecord] = {}
    for artifact in artifacts:
        raw_binding = artifact.metadata.get("graph_artifact_binding")
        if not isinstance(raw_binding, Mapping):
            raise GraphStorageIndexError(
                GraphStorageIndexErrorCode.INDEX_CORRUPT,
                "Graph index manifest artifact binding is missing",
                field=f"artifacts.{artifact.artifact_key}",
            )
        try:
            binding = GraphArtifactBindingProjection.from_dict(raw_binding)
            record = GraphArtifactIndexRecord.from_artifact_binding(
                identity=snapshot.identity,
                artifact=artifact,
                binding=binding,
            )
        except (TypeError, ValueError) as exc:
            raise GraphStorageIndexError(
                GraphStorageIndexErrorCode.INDEX_CORRUPT,
                "Graph index manifest artifact binding is invalid",
                field=f"artifacts.{artifact.artifact_key}",
            ) from exc
        expected[artifact.artifact_key] = record

    actual = {record.artifact_key: record for record in snapshot.artifact_records}
    if set(actual) != set(expected):
        raise GraphStorageIndexError(
            GraphStorageIndexErrorCode.INDEX_CORRUPT,
            "Graph index artifact set does not match the terminal manifest",
            field="artifacts",
        )
    for artifact_key, expected_record in expected.items():
        if actual[artifact_key] != expected_record:
            raise GraphStorageIndexError(
                GraphStorageIndexErrorCode.INDEX_CORRUPT,
                "Graph index artifact record conflicts with the terminal manifest",
                field=f"artifacts.{artifact_key}",
            )


__all__ = ["GraphStorageIndexReader", "GraphStorageIndexReaderPort"]
