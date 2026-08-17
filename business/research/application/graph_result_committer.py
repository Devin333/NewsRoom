from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import datetime
from types import MappingProxyType
from typing import Any

from framework.events.canonical import checksum_for
from framework.harness.control_plane.errors import HarnessValidationError
from framework.harness.control_plane.event import HarnessEvent, HarnessEventType
from framework.harness.control_plane.graph_runtime import HarnessGraphActivity
from framework.harness.ports import HarnessTransitionPort
from framework.harness.runtime.graph_result_runtime import HarnessGraphResultRuntime
from framework.harness.runtime.materializer import ResultMaterializer
from framework.harness.runtime.result_models import (
    ArtifactClass,
    BoundedSummary,
    ContextPolicy,
    NodeResultBinding,
    NodeResultEnvelope,
    NodeResultStatus,
    ResultProvenance,
    ResultSensitivity,
    RetentionClass,
)
from framework.harness.runtime.result_policy import (
    GraphArtifactPersistenceConfig,
    GraphArtifactRolloutMode,
    NodeResultRequest,
    PersistencePolicy,
)
from framework.harness.runtime.subagent_result_adapter import (
    HarnessSubAgentResultAdapter,
    subagent_result_attempt_id,
)
from framework.harness.subagents.models import SubAgentInvocation
from framework.harness.subagents.runtime import subagent_attempt_identity
from framework.harness.task_plan.models import (
    ResolvedTaskSpec,
    TaskInstance,
    TaskLifecycle,
    ValidatedTaskPlan,
)
from framework.harness.task_plan.ports import TaskPlanResultVerifierPort
from framework.harness.task_plan.store import TaskResultRecord
from framework.harness.task_plan.verification import (
    TaskPlanResultVerificationRequest,
    task_plan_subagent_attempt_identity,
)
from framework.harness.graph.model import (
    HarnessExecutableNode,
    NormalizedHarnessGraph,
)
from framework.harness.workers.result import (
    HarnessWorkerResult,
    HarnessWorkerStatus,
)
from framework.shared.time import format_datetime


RESEARCH_GRAPH_RESULT_ADAPTER_REF = "research.graph-result-adapter@1"
RESEARCH_GRAPH_RESULT_SCHEMA = "research.graph-node-result@1"
RESEARCH_WORKER_CANDIDATE_SCHEMA = "newsroom.research-worker-candidate@1"
RESEARCH_GRAPH_RESULT_SHADOW_SCHEMA = (
    "newsroom.research-graph-result-shadow-observation/v1"
)
_RESEARCH_GRAPH_IDS = frozenset(
    {
        "research.paper_analysis.graph",
        "research.paper_analysis.dynamic.graph",
    }
)
_RESEARCH_RESULT_AUTHORITY_FIELDS = frozenset(
    {
        "artifact_class",
        "cache_eligible",
        "cache_refs",
        "cache_ttl",
        "cache_ttl_seconds",
        "dependency_digest",
        "materialization_mode",
        "materialized_refs",
        "persistence",
        "persistence_decision",
        "persistence_mode",
        "persistence_policy_version",
        "quota_override",
        "required_for_publication",
        "required_for_replay",
        "result_persistence",
        "result_retention",
        "reusable",
        "retention",
        "retention_class",
        "side_effect_free",
        "storage_class",
        "storage_tier",
    }
)


@dataclass(frozen=True, slots=True)
class ResearchNodeResultPolicy:
    node_id: str
    artifact_class: ArtifactClass
    retention_class: RetentionClass
    context_policy: ContextPolicy
    required_for_publication: bool = False
    side_effect_free: bool = True

    def __post_init__(self) -> None:
        if not isinstance(self.node_id, str) or not self.node_id.strip():
            raise TypeError("node_id must be a non-blank string")
        if not isinstance(self.artifact_class, ArtifactClass):
            raise TypeError("artifact_class must be ArtifactClass")
        if not isinstance(self.retention_class, RetentionClass):
            raise TypeError("retention_class must be RetentionClass")
        if not isinstance(self.context_policy, ContextPolicy):
            raise TypeError("context_policy must be ContextPolicy")
        if not isinstance(self.required_for_publication, bool):
            raise TypeError("required_for_publication must be boolean")
        if not isinstance(self.side_effect_free, bool):
            raise TypeError("side_effect_free must be boolean")

    def to_dict(self) -> dict[str, Any]:
        return {
            "node_id": self.node_id,
            "artifact_class": self.artifact_class.value,
            "retention_class": self.retention_class.value,
            "context_policy": self.context_policy.value,
            "required_for_replay": True,
            "required_for_publication": self.required_for_publication,
            "reusable": False,
            "side_effect_free": self.side_effect_free,
            "sensitivity": ResultSensitivity.INTERNAL.value,
        }


def _policy(
    node_id: str,
    artifact_class: ArtifactClass,
    retention_class: RetentionClass,
    *,
    context_policy: ContextPolicy = ContextPolicy.REF_LOAD_ALLOWED,
    required_for_publication: bool = False,
    side_effect_free: bool = True,
) -> ResearchNodeResultPolicy:
    return ResearchNodeResultPolicy(
        node_id=node_id,
        artifact_class=artifact_class,
        retention_class=retention_class,
        context_policy=context_policy,
        required_for_publication=required_for_publication,
        side_effect_free=side_effect_free,
    )


RESEARCH_NODE_RESULT_POLICIES: Mapping[str, ResearchNodeResultPolicy] = (
    MappingProxyType(
        {
            "load_paper_source": _policy(
                "load_paper_source",
                ArtifactClass.EVIDENCE,
                RetentionClass.EVIDENCE,
                side_effect_free=False,
            ),
            "compile_document": _policy(
                "compile_document",
                ArtifactClass.EVIDENCE,
                RetentionClass.EVIDENCE,
                side_effect_free=False,
            ),
            "run_research_rag": _policy(
                "run_research_rag",
                ArtifactClass.INTERMEDIATE,
                RetentionClass.RUN,
                context_policy=ContextPolicy.SUMMARY_ONLY,
                side_effect_free=False,
            ),
            "build_evidence_pack": _policy(
                "build_evidence_pack",
                ArtifactClass.EVIDENCE,
                RetentionClass.EVIDENCE,
            ),
            "analyze_structure": _policy(
                "analyze_structure",
                ArtifactClass.INTERMEDIATE,
                RetentionClass.RUN,
                context_policy=ContextPolicy.SUMMARY_ONLY,
            ),
            "analyze_contribution": _policy(
                "analyze_contribution",
                ArtifactClass.INTERMEDIATE,
                RetentionClass.RUN,
                context_policy=ContextPolicy.SUMMARY_ONLY,
            ),
            "analyze_experiments": _policy(
                "analyze_experiments",
                ArtifactClass.INTERMEDIATE,
                RetentionClass.RUN,
                context_policy=ContextPolicy.SUMMARY_ONLY,
            ),
            "dynamic_analysis_stage": _policy(
                "dynamic_analysis_stage",
                ArtifactClass.INTERMEDIATE,
                RetentionClass.RUN,
                context_policy=ContextPolicy.SUMMARY_ONLY,
            ),
            "verify_claims": _policy(
                "verify_claims",
                ArtifactClass.EVIDENCE,
                RetentionClass.EVIDENCE,
            ),
            "quality_gate": _policy(
                "quality_gate",
                ArtifactClass.EVIDENCE,
                RetentionClass.EVIDENCE,
            ),
            "build_reader_payload": _policy(
                "build_reader_payload",
                ArtifactClass.INTERMEDIATE,
                RetentionClass.RUN,
                context_policy=ContextPolicy.SUMMARY_ONLY,
            ),
            "build_paper_card": _policy(
                "build_paper_card",
                ArtifactClass.INTERMEDIATE,
                RetentionClass.RUN,
                context_policy=ContextPolicy.SUMMARY_ONLY,
            ),
            "publish_artifacts": _policy(
                "publish_artifacts",
                ArtifactClass.REPORT,
                RetentionClass.REPORT,
                context_policy=ContextPolicy.REF_LOAD_ALLOWED,
                required_for_publication=True,
                side_effect_free=False,
            ),
        }
    )
)


def research_node_result_policy(node_id: str) -> ResearchNodeResultPolicy:
    policy = RESEARCH_NODE_RESULT_POLICIES.get(node_id)
    if policy is None:
        raise HarnessValidationError(
            "Research graph activity has no trusted result policy",
            code="research_result_policy_missing",
            details={"node_id": node_id},
        )
    return policy


class ResearchGraphResultRequestFactory:
    """Map trusted Research graph nodes to immutable persistence requests."""

    def __init__(
        self,
        policies: Mapping[str, ResearchNodeResultPolicy] = (
            RESEARCH_NODE_RESULT_POLICIES
        ),
    ) -> None:
        normalized = dict(policies)
        if not normalized or any(
            not isinstance(node_id, str)
            or not node_id
            or not isinstance(policy, ResearchNodeResultPolicy)
            or policy.node_id != node_id
            for node_id, policy in normalized.items()
        ):
            raise TypeError("policies must map node ids to Research policies")
        self._policies = MappingProxyType(dict(sorted(normalized.items())))

    @property
    def policies(self) -> Mapping[str, ResearchNodeResultPolicy]:
        return self._policies

    def validate_graph(self, graph: NormalizedHarnessGraph) -> None:
        if not isinstance(graph, NormalizedHarnessGraph):
            raise TypeError("graph must be NormalizedHarnessGraph")
        if graph.graph_id not in _RESEARCH_GRAPH_IDS:
            raise HarnessValidationError(
                "Research result persistence received an unsupported graph",
                code="research_result_graph_unsupported",
                details={"graph_id": graph.graph_id},
            )
        executable = {
            node.node_id
            for node in graph.nodes
            if isinstance(node, HarnessExecutableNode)
        }
        missing = tuple(sorted(executable.difference(self._policies)))
        if missing:
            raise HarnessValidationError(
                "Research graph has executable nodes without result policies",
                code="research_graph_result_policy_missing",
                details={"nodes": list(missing)},
            )

    def build_request(
        self,
        *,
        activity: HarnessGraphActivity,
        graph: NormalizedHarnessGraph,
        binding: NodeResultBinding,
        worker_result: HarnessWorkerResult,
        occurred_at: datetime,
    ) -> NodeResultRequest:
        self.validate_graph(graph)
        if not isinstance(activity, HarnessGraphActivity):
            raise TypeError("activity must be HarnessGraphActivity")
        if not isinstance(binding, NodeResultBinding):
            raise TypeError("binding must be NodeResultBinding")
        if not isinstance(worker_result, HarnessWorkerResult):
            raise TypeError("worker_result must be HarnessWorkerResult")
        policy = self._policies.get(activity.node_id)
        if policy is None:
            raise HarnessValidationError(
                "Research graph activity has no trusted result policy",
                code="research_result_policy_missing",
                details={"node_id": activity.node_id},
            )
        if binding.node_id != activity.node_id:
            raise HarnessValidationError(
                "Research result binding changed before materialization",
                code="graph_result_lineage_scope_mismatch",
            )
        _reject_worker_authority(worker_result)
        candidate = {
            "candidate_schema_ref": RESEARCH_WORKER_CANDIDATE_SCHEMA,
            "worker_result": worker_result.candidate_payload(),
        }
        projection = {
            "candidate_artifact_count": len(worker_result.artifacts),
            "candidate_evidence_count": len(worker_result.evidence),
            "has_diagnostics": bool(worker_result.diagnostics),
            "has_error": worker_result.error is not None,
            "worker_candidate_ref": worker_result.candidate_result_ref,
            "worker_status": worker_result.status.value,
        }
        output_schema_ref = (
            f"research.graph-node-result.{activity.node_id}@1"
        )
        return NodeResultRequest(
            binding=binding,
            status=_node_result_status(worker_result.status),
            output_schema_ref=output_schema_ref,
            output_schema_digest=checksum_for(
                {
                    "schema": RESEARCH_GRAPH_RESULT_SCHEMA,
                    "candidate_schema": RESEARCH_WORKER_CANDIDATE_SCHEMA,
                    "node_id": activity.node_id,
                    "candidate_fields": [
                        "artifacts",
                        "diagnostics",
                        "error",
                        "evidence",
                        "metrics",
                        "output",
                        "status",
                    ],
                    "policy": policy.to_dict(),
                }
            ),
            candidate={"worker_candidate": candidate},
            media_type="application/json",
            summary=BoundedSummary.from_text(
                _summary_text(activity.node_id, worker_result),
                complete=(
                    worker_result.status is HarnessWorkerStatus.SUCCEEDED
                ),
            ),
            inline_projection=projection,
            inline_allowed_fields=tuple(sorted(projection)),
            provenance=ResultProvenance(
                producer_ref=RESEARCH_GRAPH_RESULT_ADAPTER_REF,
                producer_revision=RESEARCH_GRAPH_RESULT_ADAPTER_REF,
                source_refs=(activity.input_ref,),
            ),
            artifact_class=policy.artifact_class,
            retention_class=policy.retention_class,
            sensitivity=ResultSensitivity.INTERNAL,
            required_for_replay=True,
            required_for_publication=policy.required_for_publication,
            reusable=False,
            side_effect_free=policy.side_effect_free,
            dependency_digest=None,
            context_policy=policy.context_policy,
            created_at=occurred_at,
        )


class ResearchGraphResultCommitter:
    """Commit enforced/read-only Research results through the common runtime."""

    def __init__(
        self,
        *,
        materializer: ResultMaterializer,
        graph_result_runtime: HarnessGraphResultRuntime,
        config: GraphArtifactPersistenceConfig,
        tenant_id: str,
        tenant_scope_ref: str,
        request_factory: ResearchGraphResultRequestFactory | None = None,
        context_fingerprint_resolver: Callable[[str], str | None] | None = None,
    ) -> None:
        if not isinstance(materializer, ResultMaterializer):
            raise TypeError("materializer must be ResultMaterializer")
        if not isinstance(graph_result_runtime, HarnessGraphResultRuntime):
            raise TypeError(
                "graph_result_runtime must be HarnessGraphResultRuntime"
            )
        if not isinstance(config, GraphArtifactPersistenceConfig):
            raise TypeError("config must be GraphArtifactPersistenceConfig")
        if config.mode not in {
            GraphArtifactRolloutMode.ENFORCE,
            GraphArtifactRolloutMode.READ_ONLY,
        }:
            raise HarnessValidationError(
                "Research graph result committer requires enforce or read_only",
                code="research_graph_result_rollout_invalid",
            )
        _validate_tenant_scope(tenant_id, tenant_scope_ref)
        if request_factory is not None and not isinstance(
            request_factory,
            ResearchGraphResultRequestFactory,
        ):
            raise TypeError(
                "request_factory must be ResearchGraphResultRequestFactory"
            )
        if context_fingerprint_resolver is not None and not callable(
            context_fingerprint_resolver
        ):
            raise TypeError("context_fingerprint_resolver must be callable")
        self._materializer = materializer
        self._graph_result_runtime = graph_result_runtime
        self._config = config
        self._tenant_id = tenant_id
        self._tenant_scope_ref = tenant_scope_ref
        self._request_factory = (
            request_factory or ResearchGraphResultRequestFactory()
        )
        self._context_fingerprint_resolver = context_fingerprint_resolver

    def commit_result(
        self,
        *,
        activity: HarnessGraphActivity,
        graph: NormalizedHarnessGraph,
        run_spec_checksum: str,
        worker_result: HarnessWorkerResult,
        occurred_at: datetime,
    ) -> HarnessGraphState:
        binding = self._graph_result_runtime.binding_for_activity(
            activity_id=activity.activity_id,
            graph=graph,
            tenant_id=self._tenant_id,
            tenant_scope_ref=self._tenant_scope_ref,
            attempt_id=_research_attempt_id(activity),
            run_spec_checksum=run_spec_checksum,
        )
        request = self._request_factory.build_request(
            activity=activity,
            graph=graph,
            binding=binding,
            worker_result=worker_result,
            occurred_at=occurred_at,
        )
        envelope = (
            self._materializer.materialize(request).envelope
            if self._config.mode is GraphArtifactRolloutMode.ENFORCE
            else self._materializer.require_existing(request)
        )
        return self._graph_result_runtime.accept_materialized_result(
            envelope,
            expected_binding=binding,
            activity_id=activity.activity_id,
            graph=graph,
            run_spec_checksum=run_spec_checksum,
            occurred_at=occurred_at,
            context_fingerprint=(
                None
                if self._context_fingerprint_resolver is None
                else self._context_fingerprint_resolver(activity.node_id)
            ),
        )


class ResearchGraphResultShadowObserver:
    """Record deterministic dry-run evidence while legacy remains authoritative."""

    def __init__(
        self,
        *,
        graph_result_runtime: HarnessGraphResultRuntime,
        event_port: HarnessTransitionPort,
        config: GraphArtifactPersistenceConfig,
        tenant_id: str,
        tenant_scope_ref: str,
        request_factory: ResearchGraphResultRequestFactory | None = None,
    ) -> None:
        if not isinstance(graph_result_runtime, HarnessGraphResultRuntime):
            raise TypeError(
                "graph_result_runtime must be HarnessGraphResultRuntime"
            )
        if not isinstance(event_port, HarnessTransitionPort):
            raise TypeError("event_port must implement HarnessTransitionPort")
        if not isinstance(config, GraphArtifactPersistenceConfig):
            raise TypeError("config must be GraphArtifactPersistenceConfig")
        if config.mode is not GraphArtifactRolloutMode.SHADOW:
            raise HarnessValidationError(
                "Research shadow observer requires shadow rollout mode",
                code="research_graph_result_rollout_invalid",
            )
        _validate_tenant_scope(tenant_id, tenant_scope_ref)
        if request_factory is not None and not isinstance(
            request_factory,
            ResearchGraphResultRequestFactory,
        ):
            raise TypeError(
                "request_factory must be ResearchGraphResultRequestFactory"
            )
        self._graph_result_runtime = graph_result_runtime
        self._event_port = event_port
        self._config = config
        self._tenant_id = tenant_id
        self._tenant_scope_ref = tenant_scope_ref
        self._request_factory = (
            request_factory or ResearchGraphResultRequestFactory()
        )
        self._policy = PersistencePolicy(config)

    def observe_result(
        self,
        *,
        activity: HarnessGraphActivity,
        graph: NormalizedHarnessGraph,
        run_spec_checksum: str,
        worker_result: HarnessWorkerResult,
        occurred_at: datetime,
    ) -> HarnessEvent:
        binding = self._graph_result_runtime.binding_for_activity(
            activity_id=activity.activity_id,
            graph=graph,
            tenant_id=self._tenant_id,
            tenant_scope_ref=self._tenant_scope_ref,
            attempt_id=_research_attempt_id(activity),
            run_spec_checksum=run_spec_checksum,
        )
        request = self._request_factory.build_request(
            activity=activity,
            graph=graph,
            binding=binding,
            worker_result=worker_result,
            occurred_at=occurred_at,
        )
        evaluation = self._policy.evaluate(request)
        event = self._event_port.record(
            HarnessEvent(
                event_type=HarnessEventType.DECISION_RECORDED,
                run_id=activity.run_id,
                step_id=activity.node_id,
                occurred_at=occurred_at,
                payload={
                    "decision_type": "evaluate_result_persistence",
                    "decided_by": "harness",
                    "decided_at": format_datetime(occurred_at),
                    "payload": {
                        "schema_version": RESEARCH_GRAPH_RESULT_SHADOW_SCHEMA,
                        "rollout_mode": GraphArtifactRolloutMode.SHADOW.value,
                        "binding": binding.to_dict(),
                        "candidate_checksum": request.candidate_checksum,
                        "candidate_bytes": request.candidate_bytes,
                        "worker_candidate_ref": worker_result.candidate_result_ref,
                        "legacy_payload_ref": checksum_for(worker_result.to_dict()),
                        "artifact_class": request.artifact_class.value,
                        "retention_class": request.retention_class.value,
                        "persistence_mode": evaluation.decision.mode.value,
                        "persistence_reason": evaluation.decision.reason.value,
                        "policy_version": evaluation.decision.policy_version,
                        "required": evaluation.decision.required,
                    },
                },
            )
        )
        if not isinstance(event, HarnessEvent):
            raise HarnessValidationError(
                "Research shadow observation was not durably recorded",
                code="research_graph_result_shadow_record_failed",
            )
        return event


class ResearchTaskPlanResultMaterializer(TaskPlanResultVerifierPort):
    """Materialize verified TaskPlan child transcripts before result commit."""

    def __init__(
        self,
        *,
        verifier: TaskPlanResultVerifierPort,
        adapter: HarnessSubAgentResultAdapter,
        config: GraphArtifactPersistenceConfig,
        tenant_id: str,
        tenant_scope_ref: str,
        invocation_factory: Callable[
            [ValidatedTaskPlan, ResolvedTaskSpec, TaskInstance],
            SubAgentInvocation,
        ],
        legacy_graph_id: str | None = None,
        legacy_graph_version: str | None = None,
    ) -> None:
        if not isinstance(verifier, TaskPlanResultVerifierPort):
            raise TypeError("verifier must implement TaskPlanResultVerifierPort")
        if not isinstance(adapter, HarnessSubAgentResultAdapter):
            raise TypeError("adapter must be HarnessSubAgentResultAdapter")
        if config.mode not in {
            GraphArtifactRolloutMode.ENFORCE,
            GraphArtifactRolloutMode.READ_ONLY,
        }:
            raise HarnessValidationError(
                "TaskPlan result materializer requires enforce or read_only",
                code="research_graph_result_rollout_invalid",
            )
        if checksum_for(tenant_id) != tenant_scope_ref:
            raise HarnessValidationError(
                "TaskPlan result materializer tenant scope is invalid",
                code="graph_result_lineage_scope_mismatch",
            )
        if not callable(invocation_factory):
            raise TypeError("invocation_factory must be callable")
        if (legacy_graph_id is None) != (legacy_graph_version is None):
            raise HarnessValidationError(
                "legacy TaskPlan materialization Graph identity must be complete",
                code="research_graph_result_identity_invalid",
            )
        self._verifier = verifier
        self._adapter = adapter
        self._config = config
        self._tenant_id = tenant_id
        self._tenant_scope_ref = tenant_scope_ref
        self._invocation_factory = invocation_factory
        self._legacy_graph_id = legacy_graph_id
        self._legacy_graph_version = legacy_graph_version

    def verify(
        self,
        result: HarnessWorkerResult,
        *,
        task: ResolvedTaskSpec,
        request: TaskPlanResultVerificationRequest,
    ) -> TaskResultRecord:
        if not isinstance(request, TaskPlanResultVerificationRequest):
            raise TypeError("request must be TaskPlanResultVerificationRequest")
        verified = self._verifier.verify(
            result,
            task=task,
            request=request,
        )
        instance = request.instance
        plan = request.plan
        invocation = self._invocation_factory(plan, task, instance)
        identity = subagent_attempt_identity(invocation)
        expected_identity = task_plan_subagent_attempt_identity(
            plan,
            instance,
            invocation_id=invocation.invocation_id,
            child_run_id=invocation.child_run_id,
            subagent_id=identity.subagent_id,
        )
        if identity != expected_identity:
            raise HarnessValidationError(
                "Research TaskPlan materialization invocation changed accepted-plan identity",
                code="task_plan_subagent_evidence_mismatch",
            )
        if plan.is_graph_only:
            if (
                self._legacy_graph_id is not None
                or self._legacy_graph_version is not None
            ):
                raise HarnessValidationError(
                    "Graph-only TaskPlan materialization cannot use legacy Graph identity",
                    code="legacy_graph_identity_forbidden",
                )
            graph_id = plan.graph_id
            graph_version = plan.graph_ref
        else:
            if (
                self._legacy_graph_id is None
                or self._legacy_graph_version is None
            ):
                raise HarnessValidationError(
                    "legacy TaskPlan materialization requires its Graph identity",
                    code="research_graph_result_identity_invalid",
                )
            graph_id = self._legacy_graph_id
            graph_version = self._legacy_graph_version
        binding = NodeResultBinding(
            tenant_id=self._tenant_id,
            tenant_scope_ref=self._tenant_scope_ref,
            run_id=instance.run_id,
            graph_id=graph_id,
            graph_version=graph_version,
            node_id=identity.stage_id,
            attempt_id=subagent_result_attempt_id(identity),
            parent_checkpoint_ref=_task_plan_checkpoint_ref(instance),
        )
        if self._config.mode is GraphArtifactRolloutMode.ENFORCE:
            envelope = self._adapter.recover_materialization(
                invocation=invocation,
                binding=binding,
                created_at=invocation.observed_at,
            ).materialization.envelope
        else:
            envelope = self._adapter.require_existing_materialization(
                invocation=invocation,
                binding=binding,
                created_at=invocation.observed_at,
            )
        if verified.status is not TaskLifecycle.SUCCEEDED:
            return verified
        common_refs = tuple(
            item.ref
            for item in (*envelope.materialized_refs, *envelope.cache_refs)
        )
        return replace(
            verified,
            output_refs=tuple(
                sorted(set((*verified.output_refs, *common_refs)))
            ),
        )


def _node_result_status(status: HarnessWorkerStatus) -> NodeResultStatus:
    if status is HarnessWorkerStatus.SUCCEEDED:
        return NodeResultStatus.SUCCEEDED
    if status is HarnessWorkerStatus.FAILED:
        return NodeResultStatus.FAILED
    return NodeResultStatus.HALTED


def _summary_text(
    node_id: str,
    result: HarnessWorkerResult,
) -> str:
    return (
        f"Research node {node_id} returned {result.status.value}; "
        f"artifacts={len(result.artifacts)}, evidence={len(result.evidence)}, "
        f"diagnostics={'present' if result.diagnostics else 'none'}, "
        f"error={'present' if result.error is not None else 'none'}."
    )


def _reject_worker_authority(worker_result: HarnessWorkerResult) -> None:
    paths = _authority_paths(worker_result.candidate_payload())
    if paths:
        raise HarnessValidationError(
            "Research worker result must not select persistence policy",
            code="research_result_policy_authority_rejected",
            details={"forbidden_paths": list(paths)},
        )


def _authority_paths(value: Any) -> tuple[str, ...]:
    paths: list[str] = []

    def visit(item: Any, path: str) -> None:
        if isinstance(item, Mapping):
            for raw_key, child in item.items():
                key = str(raw_key)
                normalized = key.casefold().replace("-", "_")
                child_path = f"{path}.{key}"
                if normalized.endswith("_observation") or normalized in {
                    "observation",
                    "observations",
                }:
                    continue
                if normalized in _RESEARCH_RESULT_AUTHORITY_FIELDS:
                    paths.append(child_path)
                    continue
                visit(child, child_path)
            return
        if isinstance(item, Sequence) and not isinstance(
            item,
            (str, bytes, bytearray),
        ):
            for index, child in enumerate(item):
                visit(child, f"{path}[{index}]")

    visit(value, "worker_result")
    return tuple(sorted(paths))


def _validate_tenant_scope(tenant_id: str, tenant_scope_ref: str) -> None:
    if (
        not isinstance(tenant_id, str)
        or not tenant_id
        or tenant_id != tenant_id.strip()
    ):
        raise TypeError("tenant_id must be a non-blank trimmed string")
    if checksum_for(tenant_id) != tenant_scope_ref:
        raise HarnessValidationError(
            "Research result tenant scope does not match tenant identity",
            code="graph_result_lineage_scope_mismatch",
            details={"mismatches": ["tenant_scope_ref"]},
        )


def _research_attempt_id(activity: HarnessGraphActivity) -> str:
    return f"research_{activity.activity_id.removeprefix('hga_')}"


def _task_plan_checkpoint_ref(instance: TaskInstance) -> str:
    digest = instance.plan_checksum.removeprefix("sha256:")
    return (
        f"task-plan://{instance.run_id}/{instance.stage_id}/"
        f"{instance.plan_id}/{instance.plan_version}/{digest}"
    )


__all__ = [
    "RESEARCH_GRAPH_RESULT_ADAPTER_REF",
    "RESEARCH_GRAPH_RESULT_SCHEMA",
    "RESEARCH_GRAPH_RESULT_SHADOW_SCHEMA",
    "RESEARCH_WORKER_CANDIDATE_SCHEMA",
    "RESEARCH_NODE_RESULT_POLICIES",
    "ResearchGraphResultCommitter",
    "ResearchGraphResultRequestFactory",
    "ResearchGraphResultShadowObserver",
    "ResearchNodeResultPolicy",
    "ResearchTaskPlanResultMaterializer",
    "research_node_result_policy",
]
