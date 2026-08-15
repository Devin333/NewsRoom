from __future__ import annotations

from datetime import datetime

from framework.events.errors import EventIncompleteHistoryError
from framework.harness.control_plane.errors import HarnessValidationError
from framework.harness.control_plane.graph_application import (
    HarnessGraphControlPlaneRuntime,
)
from framework.harness.control_plane.graph_result_lineage import (
    HarnessGraphResultLineage,
    HarnessGraphResultLineageStatus,
)
from framework.harness.control_plane.graph_runtime import (
    HarnessGraphActivity,
    HarnessGraphActivityResult,
    HarnessGraphActivityResultStatus,
    HarnessGraphCommitKind,
    HarnessGraphProjectionCommit,
    HarnessGraphRecovery,
)
from framework.harness.runtime.graph_result_projection import (
    graph_result_lineage_from_envelope,
)
from framework.harness.runtime.result_models import NodeResultBinding, NodeResultEnvelope
from framework.harness.graph.model import NormalizedHarnessGraph


class HarnessGraphResultRuntime:
    """Bind materialized envelopes to exact GraphRuntime activity attempts."""

    def __init__(self, graph_runtime: HarnessGraphControlPlaneRuntime) -> None:
        if not isinstance(graph_runtime, HarnessGraphControlPlaneRuntime):
            raise TypeError("graph_runtime must be HarnessGraphControlPlaneRuntime")
        self._graph_runtime = graph_runtime

    def binding_for_activity(
        self,
        *,
        activity_id: str,
        graph: NormalizedHarnessGraph,
        tenant_id: str,
        tenant_scope_ref: str,
        attempt_id: str,
        run_spec_checksum: str,
    ) -> NodeResultBinding:
        """Create the trusted binding supplied to a result producer/materializer."""

        activity, _, parent = self._resolve_activity(
            activity_id,
            graph=graph,
            run_spec_checksum=run_spec_checksum,
        )
        _validate_tenant_scope(tenant_scope_ref, activity)
        return NodeResultBinding(
            tenant_id=tenant_id,
            tenant_scope_ref=tenant_scope_ref,
            run_id=activity.run_id,
            graph_id=graph.graph_id,
            graph_version=_graph_version(graph),
            node_id=activity.node_id,
            attempt_id=attempt_id,
            parent_checkpoint_ref=_checkpoint_ref(parent),
        )

    def accept_materialized_result(
        self,
        envelope: NodeResultEnvelope,
        *,
        expected_binding: NodeResultBinding,
        activity_id: str,
        graph: NormalizedHarnessGraph,
        run_spec_checksum: str,
        occurred_at: datetime,
        context_fingerprint: str | None = None,
    ):
        """Commit a materialized result cause and its adjacent bounded projection."""

        if not isinstance(envelope, NodeResultEnvelope):
            raise TypeError("envelope must be NodeResultEnvelope")
        if not isinstance(expected_binding, NodeResultBinding):
            raise TypeError("expected_binding must be NodeResultBinding")
        if envelope.binding != expected_binding:
            raise HarnessValidationError(
                "materialized result does not match its trusted Harness binding",
                code="graph_result_lineage_scope_mismatch",
            )
        activity, _, parent = self._resolve_activity(
            activity_id,
            graph=graph,
            run_spec_checksum=run_spec_checksum,
        )
        _validate_binding(
            expected_binding,
            activity,
            graph,
            parent,
        )
        lineage = graph_result_lineage_from_envelope(
            envelope,
            node_instance_id=activity.node_instance_id,
            attempt=activity.attempt,
            identity_scope_ref=activity.identity_scope_ref,
            subject_scope_ref=activity.subject_scope_ref,
            context_fingerprint=context_fingerprint,
        )
        _validate_lineage_binding(lineage, activity, graph, parent)
        result = HarnessGraphActivityResult.for_activity(
            activity,
            evidence_ref=lineage.lineage_checksum,
            payload_ref=lineage.envelope_checksum,
            status=_activity_status(lineage),
            termination_confirmed=True,
            result_lineage=lineage,
        )
        return self._graph_runtime.accept_activity_result(
            result,
            graph=graph,
            run_spec_checksum=run_spec_checksum,
            occurred_at=occurred_at,
        )

    def _resolve_activity(
        self,
        activity_id: str,
        *,
        graph: NormalizedHarnessGraph,
        run_spec_checksum: str,
    ) -> tuple[HarnessGraphActivity, HarnessGraphRecovery, HarnessGraphProjectionCommit]:
        if not isinstance(graph, NormalizedHarnessGraph):
            raise TypeError("graph must be NormalizedHarnessGraph")
        activity = self._graph_runtime.transition_port.activity_for(activity_id)
        if activity is None:
            raise HarnessValidationError(
                "materialized result references an unknown graph activity",
                code="graph_activity_identity_mismatch",
            )
        recovery = self._graph_runtime.transition_port.recover_graph(activity.run_id)
        if (
            recovery.graph != graph
            or recovery.run_spec_checksum != run_spec_checksum
            or recovery.state is None
        ):
            raise HarnessValidationError(
                "materialized result conflicts with the pinned graph run",
                code="graph_result_lineage_scope_mismatch",
            )
        parent = _activity_parent_projection(recovery, activity)
        return activity, recovery, parent


def _activity_parent_projection(
    recovery: HarnessGraphRecovery,
    activity: HarnessGraphActivity,
) -> HarnessGraphProjectionCommit:
    matches = tuple(
        item
        for item in recovery.projection_commits
        if item.commit_kind is HarnessGraphCommitKind.DECISION_PROJECTION
        and item.cause_checksum == activity.causal_decision_checksum
        and item.sequence == activity.causal_decision_sequence + 1
        and item.activity == activity
    )
    if len(matches) != 1:
        raise EventIncompleteHistoryError(
            "graph activity is missing its exact dispatch projection"
        )
    return matches[0]


def _validate_binding(
    binding: NodeResultBinding,
    activity: HarnessGraphActivity,
    graph: NormalizedHarnessGraph,
    parent: HarnessGraphProjectionCommit,
) -> None:
    mismatches = tuple(
        field_name
        for field_name, expected, actual in (
            ("run_id", activity.run_id, binding.run_id),
            ("graph_id", graph.graph_id, binding.graph_id),
            ("graph_version", _graph_version(graph), binding.graph_version),
            ("node_id", activity.node_id, binding.node_id),
            ("tenant_scope_ref", activity.tenant_scope_ref, binding.tenant_scope_ref),
            ("parent_checkpoint_ref", _checkpoint_ref(parent), binding.parent_checkpoint_ref),
        )
        if expected != actual
    )
    if mismatches:
        raise HarnessValidationError(
            "materialized result binding does not match the graph activity",
            code="graph_result_lineage_scope_mismatch",
            details={"mismatches": list(mismatches)},
        )


def _validate_tenant_scope(
    tenant_scope_ref: str,
    activity: HarnessGraphActivity,
) -> None:
    if tenant_scope_ref != activity.tenant_scope_ref:
        raise HarnessValidationError(
            "materialized result tenant scope is not authorized by the graph activity",
            code="graph_result_lineage_scope_mismatch",
            details={"mismatches": ["tenant_scope_ref"]},
        )


def _validate_lineage_binding(
    lineage: HarnessGraphResultLineage,
    activity: HarnessGraphActivity,
    graph: NormalizedHarnessGraph,
    parent: HarnessGraphProjectionCommit,
) -> None:
    mismatches = tuple(
        field_name
        for field_name, expected, actual in (
            ("run_id", activity.run_id, lineage.run_id),
            ("graph_id", graph.graph_id, lineage.graph_id),
            ("graph_version", _graph_version(graph), lineage.graph_version),
            ("node_id", activity.node_id, lineage.node_id),
            ("node_instance_id", activity.node_instance_id, lineage.node_instance_id),
            ("attempt", activity.attempt, lineage.attempt),
            ("parent_checkpoint_ref", _checkpoint_ref(parent), lineage.parent_checkpoint_ref),
            ("tenant_scope_ref", activity.tenant_scope_ref, lineage.tenant_scope_ref),
            ("identity_scope_ref", activity.identity_scope_ref, lineage.identity_scope_ref),
            ("subject_scope_ref", activity.subject_scope_ref, lineage.subject_scope_ref),
        )
        if expected != actual
    )
    if mismatches:
        raise HarnessValidationError(
            "materialized result lineage does not match the graph activity",
            code="graph_result_lineage_activity_mismatch",
            details={"mismatches": list(mismatches)},
        )


def _graph_version(graph: NormalizedHarnessGraph) -> str:
    return f"{graph.graph_id}@{graph.workflow_version}"


def _checkpoint_ref(commit: HarnessGraphProjectionCommit) -> str:
    checksum = commit.state.projection_checksum.removeprefix("sha256:")
    return f"checkpoint://{commit.state.run_id}/{commit.sequence}/{checksum}"


def _activity_status(lineage: HarnessGraphResultLineage) -> HarnessGraphActivityResultStatus:
    if lineage.status is HarnessGraphResultLineageStatus.SUCCEEDED:
        return HarnessGraphActivityResultStatus.SUCCEEDED
    if lineage.status is HarnessGraphResultLineageStatus.SKIPPED:
        return HarnessGraphActivityResultStatus.CANCELLED
    if lineage.status is HarnessGraphResultLineageStatus.FAILED:
        return HarnessGraphActivityResultStatus.FAILED
    return HarnessGraphActivityResultStatus.INDETERMINATE


__all__ = ["HarnessGraphResultRuntime"]
