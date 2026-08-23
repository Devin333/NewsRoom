"""Active Graph storage index candidate construction.

The builder is intentionally independent from the inactive candidate adapter.
It accepts a canonical terminal manifest plus authoritative event history and
keeps run/system artifacts separate from node-produced artifacts.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping

from framework.agent.artifacts.paths import (
    ArtifactPathError,
    validate_relative_artifact_path,
)
from framework.events.canonical import StoredEvent
from framework.events.errors import EventContractError
from framework.events.projection import GraphEventContext, graph_event_context
from framework.harness.artifacts import (
    GraphTerminalManifestV2,
    graph_terminal_manifest_hash,
)
from framework.shared.graph_identity import GraphRunIdentity
from infrastructure.storage.indexing.bindings import (
    GraphArtifactBindingKind,
    GraphArtifactBindingProjection,
)
from infrastructure.storage.indexing.contracts import (
    GraphArtifactIndexRecord,
    GraphEventIndexRecord,
    GraphStorageIndexCandidate,
    GraphStorageIndexError,
    GraphStorageIndexErrorCode,
    GraphStorageIndexIdentity,
    GraphStorageIndexMaterializationRequest,
)


class GraphStorageIndexCandidateBuilder:
    """Build a live index candidate from exact Graph-owned evidence."""

    def build(
        self,
        request: GraphStorageIndexMaterializationRequest,
    ) -> GraphStorageIndexCandidate:
        if not isinstance(request, GraphStorageIndexMaterializationRequest):
            raise TypeError(
                "request must be GraphStorageIndexMaterializationRequest"
            )
        if request.manifest.manifest_hash != graph_terminal_manifest_hash(
            request.manifest,
        ):
            _reject(
                GraphStorageIndexErrorCode.REQUEST_INVALID,
                "Graph terminal manifest checksum is invalid",
                field="manifest_hash",
            )
        identity = _identity_from_manifest(request.manifest)
        contexts = self._validate_events(request, identity)
        bindings = self._validate_bindings(request, contexts)
        artifact_records = tuple(
            GraphArtifactIndexRecord.from_artifact_binding(
                identity=identity,
                artifact=artifact,
                binding=bindings[artifact.artifact_id],
            )
            for artifact in request.manifest.artifacts
        )
        event_records = tuple(
            GraphEventIndexRecord.from_event(
                identity=identity,
                event=event,
                context=contexts[event.event_id],
            )
            for event in request.events
        )
        return GraphStorageIndexCandidate(
            identity=identity,
            artifact_records=artifact_records,
            event_records=event_records,
        )

    @staticmethod
    def from_manifest(
        *,
        manifest: GraphTerminalManifestV2,
        events: tuple[StoredEvent, ...],
    ) -> GraphStorageIndexMaterializationRequest:
        """Extract only checksum-bound binding projections from a manifest."""

        bindings: list[GraphArtifactBindingProjection] = []
        for artifact in manifest.artifacts:
            metadata = artifact.metadata
            raw_binding = (
                metadata.get("graph_artifact_binding")
                if isinstance(metadata, Mapping)
                else None
            )
            if not isinstance(raw_binding, Mapping):
                _reject(
                    GraphStorageIndexErrorCode.REQUEST_INVALID,
                    "Graph artifact is missing its explicit binding projection",
                    field=f"artifact_bindings.{artifact.artifact_id}",
                )
            try:
                bindings.append(GraphArtifactBindingProjection.from_dict(raw_binding))
            except (TypeError, ValueError) as exc:
                raise GraphStorageIndexError(
                    GraphStorageIndexErrorCode.REQUEST_INVALID,
                    "Graph artifact binding projection is invalid",
                    field=f"artifact_bindings.{artifact.artifact_id}",
                ) from exc
        return GraphStorageIndexMaterializationRequest(
            manifest=manifest,
            events=events,
            artifact_bindings=tuple(bindings),
        )

    @staticmethod
    def _validate_events(
        request: GraphStorageIndexMaterializationRequest,
        identity: GraphStorageIndexIdentity,
    ) -> dict[str, GraphEventContext]:
        if not request.events:
            _reject(
                GraphStorageIndexErrorCode.CANDIDATE_NOT_QUALIFIED,
                "Graph index candidate requires non-empty durable event history",
                field="events",
            )
        expected_sequences = tuple(range(1, len(request.events) + 1))
        actual_sequences = tuple(
            event.stream_sequence for event in request.events
        )
        if actual_sequences != expected_sequences:
            _reject(
                GraphStorageIndexErrorCode.CANDIDATE_NOT_QUALIFIED,
                "Graph index event history is not a contiguous prefix",
                field="events",
            )
        event_ids = tuple(event.event_id for event in request.events)
        if len(event_ids) != len(set(event_ids)):
            _reject(
                GraphStorageIndexErrorCode.CANDIDATE_NOT_QUALIFIED,
                "Graph index event history contains duplicate event ids",
                field="events",
            )

        contexts: dict[str, GraphEventContext] = {}
        node_instances: dict[str, str] = {}
        for event in request.events:
            try:
                event.verify_integrity()
            except EventContractError as exc:
                raise GraphStorageIndexError(
                    GraphStorageIndexErrorCode.CANDIDATE_NOT_QUALIFIED,
                    "Graph index event integrity verification failed",
                    field=f"events.{event.event_id}",
                ) from exc
            if (
                event.stream_id != f"run:{identity.run_id}"
                or event.tenant_id != identity.tenant_id
            ):
                _reject(
                    GraphStorageIndexErrorCode.CANDIDATE_NOT_QUALIFIED,
                    "Graph index event is outside the manifest scope",
                    field=f"events.{event.event_id}",
                )
            try:
                context = graph_event_context(event)
            except (EventContractError, TypeError, ValueError) as exc:
                raise GraphStorageIndexError(
                    GraphStorageIndexErrorCode.CANDIDATE_NOT_QUALIFIED,
                    "Graph index event context is invalid",
                    field=f"events.{event.event_id}",
                ) from exc
            if context.identity != identity.graph_identity:
                _reject(
                    GraphStorageIndexErrorCode.CANDIDATE_NOT_QUALIFIED,
                    "Graph index event Graph identity does not match the manifest",
                    field=f"events.{event.event_id}",
                )
            contexts[event.event_id] = context
            if context.node_instance_id is None:
                continue
            existing_node = node_instances.get(context.node_instance_id)
            if existing_node is not None and existing_node != context.node_id:
                _reject(
                    GraphStorageIndexErrorCode.CANDIDATE_NOT_QUALIFIED,
                    "Graph index event history assigns one node instance to multiple nodes",
                    field=f"events.{event.event_id}",
                )
            if context.node_id is not None:
                node_instances[context.node_instance_id] = context.node_id
        return contexts

    @staticmethod
    def _validate_bindings(
        request: GraphStorageIndexMaterializationRequest,
        contexts: dict[str, GraphEventContext],
    ) -> dict[str, GraphArtifactBindingProjection]:
        grouped: dict[str, list[GraphArtifactBindingProjection]] = defaultdict(list)
        for raw_binding in request.artifact_bindings:
            try:
                binding = GraphArtifactBindingProjection.from_dict(
                    raw_binding.to_dict(),
                )
            except (TypeError, ValueError) as exc:
                raise GraphStorageIndexError(
                    GraphStorageIndexErrorCode.REQUEST_INVALID,
                    "Graph artifact binding projection checksum is invalid",
                    field="artifact_bindings",
                ) from exc
            grouped[binding.artifact_id].append(binding)

        artifacts = {
            artifact.artifact_id: artifact
            for artifact in request.manifest.artifacts
        }
        extra_ids = sorted(set(grouped).difference(artifacts))
        if extra_ids:
            _reject(
                GraphStorageIndexErrorCode.REQUEST_INVALID,
                "Graph artifact binding references an artifact outside the manifest",
                field="artifact_bindings",
            )
        bindings: dict[str, GraphArtifactBindingProjection] = {}
        node_instances = {
            context.node_instance_id: context.node_id
            for context in contexts.values()
            if context.node_instance_id is not None
        }
        for artifact in request.manifest.artifacts:
            try:
                validate_relative_artifact_path(
                    artifact.relative_path,
                    field="Graph artifact index relative_path",
                )
            except ArtifactPathError as exc:
                raise GraphStorageIndexError(
                    GraphStorageIndexErrorCode.REQUEST_INVALID,
                    "Graph artifact index path is invalid",
                    field=f"artifacts.{artifact.artifact_id}.relative_path",
                ) from exc
            values = grouped.get(artifact.artifact_id, [])
            if len(values) != 1:
                _reject(
                    GraphStorageIndexErrorCode.REQUEST_INVALID,
                    "Graph manifest artifact must have exactly one binding projection",
                    field=f"artifact_bindings.{artifact.artifact_id}",
                )
            binding = values[0]
            if binding.kind is GraphArtifactBindingKind.NODE:
                if node_instances.get(binding.node_instance_id) != binding.node_id:
                    _reject(
                        GraphStorageIndexErrorCode.CANDIDATE_NOT_QUALIFIED,
                        "Graph node artifact binding is not proven by event history",
                        field=f"artifact_bindings.{artifact.artifact_id}",
                    )
            bindings[artifact.artifact_id] = binding
        return bindings


def _reject(
    code: GraphStorageIndexErrorCode,
    message: str,
    *,
    field: str,
) -> None:
    raise GraphStorageIndexError(code, message, field=field)


def _identity_from_manifest(
    manifest: GraphTerminalManifestV2,
) -> GraphStorageIndexIdentity:
    if manifest.manifest_hash is None:
        _reject(
            GraphStorageIndexErrorCode.REQUEST_INVALID,
            "Graph terminal manifest has no canonical hash",
            field="manifest_hash",
        )
    return GraphStorageIndexIdentity(
        tenant_id=manifest.tenant_id,
        graph_identity=GraphRunIdentity(
            run_id=manifest.run_id,
            graph_id=manifest.graph_id,
            graph_version=manifest.graph_version,
            graph_ref=f"{manifest.graph_id}@{manifest.graph_version}",
            graph_checksum=manifest.normalized_graph_checksum,
        ),
        terminal_manifest_hash=manifest.manifest_hash,
    )


__all__ = ["GraphStorageIndexCandidateBuilder"]
