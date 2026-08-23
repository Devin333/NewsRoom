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
from framework.events.ports import EventReaderPort
from framework.events.projection import GraphEventContext, graph_event_context
from framework.events.runtime.models import MAX_PAGE_LIMIT, StreamReadRequest
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
    MAX_GRAPH_INDEX_EVENTS,
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


class GraphStorageIndexCandidateMaterializer:
    """Read one pinned durable event prefix before building the candidate."""

    def __init__(
        self,
        *,
        event_reader: EventReaderPort,
        builder: GraphStorageIndexCandidateBuilder | None = None,
        page_size: int = 100,
    ) -> None:
        if not isinstance(event_reader, EventReaderPort):
            raise TypeError("event_reader must implement EventReaderPort")
        if isinstance(page_size, bool) or not isinstance(page_size, int):
            raise TypeError("page_size must be an integer")
        if page_size < 1 or page_size > MAX_PAGE_LIMIT:
            raise ValueError(f"page_size must be between 1 and {MAX_PAGE_LIMIT}")
        self.event_reader = event_reader
        self.builder = builder or GraphStorageIndexCandidateBuilder()
        self.page_size = page_size

    def materialize(self, manifest) -> GraphStorageIndexCandidate:
        from framework.harness.artifacts import GraphTerminalManifestV2

        if not isinstance(manifest, GraphTerminalManifestV2):
            raise TypeError("manifest must be GraphTerminalManifestV2")
        events = self._read_events(manifest)
        request = self.builder.from_manifest(manifest=manifest, events=events)
        return self.builder.build(request)

    def _read_events(self, manifest) -> tuple[StoredEvent, ...]:
        stream_id = f"run:{manifest.run_id}"
        high_watermark = self.event_reader.get_stream_high_watermark(
            stream_id,
            tenant_id=manifest.tenant_id,
        )
        if high_watermark is None:
            _reject(
                GraphStorageIndexErrorCode.CANDIDATE_NOT_QUALIFIED,
                "Graph index durable event history is empty",
                field="events",
            )
        events: list[StoredEvent] = []
        cursor = None
        while True:
            page = self.event_reader.read_stream(
                StreamReadRequest(
                    stream_id=stream_id,
                    cursor=cursor,
                    through_sequence=high_watermark,
                    limit=self.page_size,
                    tenant_id=manifest.tenant_id,
                )
            )
            if (
                page.stream_id != stream_id
                or page.tenant_id != manifest.tenant_id
                or page.high_watermark != high_watermark
            ):
                _reject(
                    GraphStorageIndexErrorCode.CANDIDATE_NOT_QUALIFIED,
                    "Graph index event page changed its pinned scope or watermark",
                    field="events",
                )
            if page.next_cursor is not None and not page.events:
                _reject(
                    GraphStorageIndexErrorCode.CANDIDATE_NOT_QUALIFIED,
                    "Graph index event reader returned an empty page with a cursor",
                    field="events",
                )
            events.extend(page.events)
            if len(events) > MAX_GRAPH_INDEX_EVENTS:
                _reject(
                    GraphStorageIndexErrorCode.REQUEST_INVALID,
                    "Graph index event history exceeds its bound",
                    field="events",
                )
            cursor = page.next_cursor
            if cursor is None:
                break
        if self.event_reader.get_stream_high_watermark(
            stream_id,
            tenant_id=manifest.tenant_id,
        ) != high_watermark:
            _reject(
                GraphStorageIndexErrorCode.CANDIDATE_NOT_QUALIFIED,
                "Graph index durable event history changed during read",
                field="events",
            )
        return tuple(events)


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


__all__ = [
    "GraphStorageIndexCandidateBuilder",
    "GraphStorageIndexCandidateMaterializer",
]
