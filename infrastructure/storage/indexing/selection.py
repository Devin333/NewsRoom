"""Canonical selection policy for terminal artifacts in the Graph index."""

from __future__ import annotations

from framework.harness.artifacts import (
    GraphTerminalArtifact,
    GraphTerminalManifestV2,
)
from infrastructure.storage.indexing.contracts import (
    GraphStorageIndexError,
    GraphStorageIndexErrorCode,
)


def graph_indexable_terminal_artifacts(
    manifest: GraphTerminalManifestV2,
) -> tuple[GraphTerminalArtifact, ...]:
    """Return the terminal-public artifacts owned by the Graph index.

    Context snapshots and Graph result references remain replay inputs of their
    dedicated stores. Their publication flag alone must not promote them into
    the public terminal index.
    """

    if not isinstance(manifest, GraphTerminalManifestV2):
        raise TypeError("manifest must be GraphTerminalManifestV2")
    artifacts = tuple(
        artifact
        for artifact in manifest.artifacts
        if artifact.required_for_publication
        and not artifact.metadata.get("context_ref_only")
        and not artifact.metadata.get("graph_result_ref_only")
    )
    if not artifacts:
        raise GraphStorageIndexError(
            GraphStorageIndexErrorCode.CANDIDATE_NOT_QUALIFIED,
            "Graph terminal manifest has no indexable publication artifacts",
            field="artifacts",
        )
    return artifacts


__all__ = ["graph_indexable_terminal_artifacts"]
