from __future__ import annotations

from collections import defaultdict

from framework.agent.artifacts.paths import (
    ArtifactPathError,
    validate_relative_artifact_path,
)
from framework.events.errors import EventContractError
from framework.events.projection import GraphEventContext, graph_event_context
from framework.harness.artifacts import graph_terminal_manifest_hash
from infrastructure.storage.indexing.contracts import (
    GraphArtifactIndexRecord,
    GraphArtifactNodeBinding,
    GraphEventIndexRecord,
    GraphIndexCandidateStageReceipt,
    GraphIndexCandidateStorePort,
    GraphIndexDiagnosticCode,
    GraphIndexDryRunDiagnostic,
    GraphStorageIndexCandidate,
    GraphStorageIndexCandidateRequest,
    GraphStorageIndexDryRunReport,
    GraphStorageIndexError,
    GraphStorageIndexErrorCode,
    GraphStorageIndexIdentity,
)


class InactiveGraphStorageIndexAdapter:
    """Gate A candidate adapter, deliberately absent from live composition."""

    def __init__(self, candidate_store: GraphIndexCandidateStorePort) -> None:
        if not isinstance(candidate_store, GraphIndexCandidateStorePort):
            raise TypeError(
                "candidate_store must implement GraphIndexCandidateStorePort"
            )
        self._candidate_store = candidate_store

    def dry_run(
        self,
        request: GraphStorageIndexCandidateRequest,
    ) -> GraphStorageIndexDryRunReport:
        if not isinstance(request, GraphStorageIndexCandidateRequest):
            raise TypeError(
                "request must be GraphStorageIndexCandidateRequest"
            )
        if (
            request.manifest.manifest_hash
            != graph_terminal_manifest_hash(request.manifest)
        ):
            return GraphStorageIndexDryRunReport(
                request_ref=request.request_ref,
                diagnostics=(
                    _diagnostic(
                        GraphIndexDiagnosticCode.MANIFEST_INTEGRITY_INVALID,
                        subject_kind="run",
                        subject_ref=request.manifest.run_id,
                        detail_code="terminal-manifest-checksum-invalid",
                    ),
                ),
            )
        identity = GraphStorageIndexIdentity.from_manifest(request.manifest)
        diagnostics: list[GraphIndexDryRunDiagnostic] = []
        contexts = self._validate_events(request, identity, diagnostics)
        bindings = self._validate_bindings(
            request,
            contexts=contexts,
            diagnostics=diagnostics,
        )
        if diagnostics:
            return GraphStorageIndexDryRunReport(
                request_ref=request.request_ref,
                diagnostics=tuple(diagnostics),
            )
        artifact_records = tuple(
            GraphArtifactIndexRecord.from_artifact(
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
        return GraphStorageIndexDryRunReport(
            request_ref=request.request_ref,
            diagnostics=(),
            candidate=GraphStorageIndexCandidate(
                identity=identity,
                artifact_records=artifact_records,
                event_records=event_records,
            ),
        )

    def stage_qualified_candidate(
        self,
        report: GraphStorageIndexDryRunReport,
    ) -> GraphIndexCandidateStageReceipt:
        if not isinstance(report, GraphStorageIndexDryRunReport):
            raise TypeError("report must be GraphStorageIndexDryRunReport")
        if not report.qualified or report.candidate is None:
            raise GraphStorageIndexError(
                GraphStorageIndexErrorCode.CANDIDATE_NOT_QUALIFIED,
                "Graph index dry-run did not qualify a candidate",
                field="report",
            )
        return self._candidate_store.stage_candidate(report.candidate)

    def read_back(
        self,
        receipt: GraphIndexCandidateStageReceipt,
    ) -> GraphStorageIndexCandidate:
        if not isinstance(receipt, GraphIndexCandidateStageReceipt):
            raise TypeError("receipt must be GraphIndexCandidateStageReceipt")
        candidate = self._candidate_store.read_candidate(receipt.candidate_ref)
        if (
            candidate.candidate_ref != receipt.candidate_ref
            or candidate.candidate_checksum != receipt.candidate_checksum
        ):
            raise GraphStorageIndexError(
                GraphStorageIndexErrorCode.CANDIDATE_SCOPE_MISMATCH,
                "Graph index candidate read-back changed the stage receipt",
                field="candidate",
            )
        return candidate

    @staticmethod
    def _validate_events(
        request: GraphStorageIndexCandidateRequest,
        identity: GraphStorageIndexIdentity,
        diagnostics: list[GraphIndexDryRunDiagnostic],
    ) -> dict[str, GraphEventContext]:
        if not request.events:
            diagnostics.append(
                _diagnostic(
                    GraphIndexDiagnosticCode.EVENT_HISTORY_EMPTY,
                    subject_kind="run",
                    subject_ref=identity.run_id,
                    detail_code="no-durable-events",
                )
            )
            return {}
        expected_sequences = tuple(range(1, len(request.events) + 1))
        actual_sequences = tuple(
            event.stream_sequence for event in request.events
        )
        if actual_sequences != expected_sequences:
            diagnostics.append(
                _diagnostic(
                    GraphIndexDiagnosticCode.EVENT_SEQUENCE_INVALID,
                    subject_kind="stream",
                    subject_ref=f"run:{identity.run_id}",
                    detail_code="non-contiguous-prefix",
                )
            )
        event_ids = tuple(event.event_id for event in request.events)
        if len(event_ids) != len(set(event_ids)):
            diagnostics.append(
                _diagnostic(
                    GraphIndexDiagnosticCode.EVENT_SEQUENCE_INVALID,
                    subject_kind="stream",
                    subject_ref=f"run:{identity.run_id}",
                    detail_code="duplicate-event-id",
                )
            )

        contexts: dict[str, GraphEventContext] = {}
        node_instances: dict[str, str] = {}
        for event in request.events:
            try:
                event.verify_integrity()
            except EventContractError:
                diagnostics.append(
                    _diagnostic(
                        GraphIndexDiagnosticCode.EVENT_INTEGRITY_INVALID,
                        subject_kind="event",
                        subject_ref=event.event_id,
                        detail_code="checksum-invalid",
                    )
                )
                continue
            if (
                event.stream_id != f"run:{identity.run_id}"
                or event.tenant_id != identity.tenant_id
            ):
                diagnostics.append(
                    _diagnostic(
                        GraphIndexDiagnosticCode.EVENT_SCOPE_MISMATCH,
                        subject_kind="event",
                        subject_ref=event.event_id,
                        detail_code="stream-or-tenant-mismatch",
                    )
                )
                continue
            try:
                context = graph_event_context(event)
            except (EventContractError, TypeError, ValueError):
                diagnostics.append(
                    _diagnostic(
                        GraphIndexDiagnosticCode.EVENT_CONTEXT_INVALID,
                        subject_kind="event",
                        subject_ref=event.event_id,
                        detail_code="graph-context-invalid",
                    )
                )
                continue
            if context.identity != identity.graph_identity:
                diagnostics.append(
                    _diagnostic(
                        GraphIndexDiagnosticCode.EVENT_GRAPH_IDENTITY_MISMATCH,
                        subject_kind="event",
                        subject_ref=event.event_id,
                        detail_code="graph-identity-mismatch",
                    )
                )
                continue
            contexts[event.event_id] = context
            if context.node_instance_id is None:
                continue
            existing_node = node_instances.get(context.node_instance_id)
            if existing_node is not None and existing_node != context.node_id:
                diagnostics.append(
                    _diagnostic(
                        GraphIndexDiagnosticCode.NODE_INSTANCE_CONFLICT,
                        subject_kind="node_instance",
                        subject_ref=context.node_instance_id,
                        detail_code="node-id-conflict",
                    )
                )
            else:
                assert context.node_id is not None
                node_instances[context.node_instance_id] = context.node_id
        return contexts

    @staticmethod
    def _validate_bindings(
        request: GraphStorageIndexCandidateRequest,
        *,
        contexts: dict[str, GraphEventContext],
        diagnostics: list[GraphIndexDryRunDiagnostic],
    ) -> dict[str, GraphArtifactNodeBinding]:
        grouped: dict[str, list[GraphArtifactNodeBinding]] = defaultdict(list)
        for binding in request.artifact_bindings:
            grouped[binding.artifact_id].append(binding)
        bindings: dict[str, GraphArtifactNodeBinding] = {}
        for artifact_id, values in grouped.items():
            if len(values) != 1:
                diagnostics.append(
                    _diagnostic(
                        GraphIndexDiagnosticCode.ARTIFACT_BINDING_DUPLICATE,
                        subject_kind="artifact",
                        subject_ref=artifact_id,
                        detail_code="duplicate-binding",
                    )
                )
                continue
            bindings[artifact_id] = values[0]

        artifacts = {
            artifact.artifact_id: artifact for artifact in request.manifest.artifacts
        }
        for artifact_id in sorted(set(bindings).difference(artifacts)):
            diagnostics.append(
                _diagnostic(
                    GraphIndexDiagnosticCode.ARTIFACT_BINDING_EXTRA,
                    subject_kind="artifact",
                    subject_ref=artifact_id,
                    detail_code="artifact-not-in-manifest",
                )
            )
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
            except ArtifactPathError:
                diagnostics.append(
                    _diagnostic(
                        GraphIndexDiagnosticCode.ARTIFACT_PATH_INVALID,
                        subject_kind="artifact",
                        subject_ref=artifact.artifact_id,
                        detail_code="relative-path-invalid",
                    )
                )
            binding = bindings.get(artifact.artifact_id)
            if binding is None:
                diagnostics.append(
                    _diagnostic(
                        GraphIndexDiagnosticCode.ARTIFACT_BINDING_MISSING,
                        subject_kind="artifact",
                        subject_ref=artifact.artifact_id,
                        detail_code="node-instance-binding-required",
                    )
                )
                continue
            if (
                binding.node_id != artifact.node_id
                or binding.attempt_id != artifact.attempt_id
            ):
                diagnostics.append(
                    _diagnostic(
                        GraphIndexDiagnosticCode.ARTIFACT_BINDING_MISMATCH,
                        subject_kind="artifact",
                        subject_ref=artifact.artifact_id,
                        detail_code="manifest-node-or-attempt-mismatch",
                    )
                )
                continue
            if node_instances.get(binding.node_instance_id) != binding.node_id:
                diagnostics.append(
                    _diagnostic(
                        GraphIndexDiagnosticCode.ARTIFACT_NODE_INSTANCE_UNVERIFIED,
                        subject_kind="artifact",
                        subject_ref=artifact.artifact_id,
                        detail_code="node-instance-not-in-event-history",
                    )
                )
        return bindings


def _diagnostic(
    code: GraphIndexDiagnosticCode,
    *,
    subject_kind: str,
    subject_ref: str,
    detail_code: str,
) -> GraphIndexDryRunDiagnostic:
    return GraphIndexDryRunDiagnostic(
        code=code,
        subject_kind=subject_kind,
        subject_ref=subject_ref,
        detail_code=detail_code,
    )


__all__ = ["InactiveGraphStorageIndexAdapter"]
