"""Application service for the production Reader Repair Graph.

The service owns Graph admission and physical dispatch wiring for one repair
run.  It deliberately accepts ports for memory, event, node-output, and
candidate generation so the business layer never imports infrastructure or
interface adapters.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from framework.events.errors import EventIncompleteHistoryError
from framework.harness import (
    HarnessBudget,
    HarnessControlPlane,
    HarnessRunResult,
    HarnessRunSpec,
    HarnessTransitionPort,
    HarnessValidationError,
)
from framework.harness.control_plane.node_output import (
    HarnessCommittedNodeOutputReceipt,
    HarnessNodeOutputResourcePort,
)
from framework.harness.graph import HarnessContractReference
from framework.harness.graph.bindings import HarnessActivityCapabilities, HarnessActivityUsage
from framework.harness.graph.compiler import HarnessGraphCompiler
from framework.harness.graph.definition import HarnessGraphDefinition
from framework.harness.graph.validation import (
    HarnessGraphPreflight,
    HarnessGraphPreflightPolicy,
)
from framework.harness.runtime import (
    HarnessCommittedNodeOutputInputResolver,
    HarnessGraphPhysicalActivityDispatcher,
    HarnessGraphPhysicalActivityExecutor,
)
from framework.harness.side_effects import (
    HarnessSideEffectHandler,
    HarnessSideEffectPreparationHandler,
    HarnessSideEffectStorePort,
)
from framework.shared.attempts import AttemptSupervisor
from framework.shared.time import utc_now
from framework.harness.control_plane.event import HarnessEventType

from backend.research.application.ask_paper import AskPaperUseCase
from backend.research.domain import (
    ResearchReaderPayload,
    research_event_tenant_id,
    research_identity_scope_ref,
    research_subject_scope_ref,
)
from backend.research.graphs.reader_repair import (
    READER_REPAIR_APPLICATION_OUTPUT_KEY,
    READER_REPAIR_COMMITTED_OUTPUT_BINDING_ID,
    build_reader_repair_graph_definition,
)
from backend.research.graphs.reader_repair_function_workers import (
    ReaderRepairRunAuthorityContext,
    build_reader_repair_function_worker_implementations,
)
from backend.research.graphs.reader_repair_runtime import (
    build_reader_repair_runtime_binding_bundle,
)
from backend.research.graphs.reader_repair_subagent_workers import (
    build_reader_repair_subagent_worker_implementations,
)
from backend.research.ports.llm_worker import ResearchCandidateWorkerPort
from backend.research.ports.repair_memory import ReaderRepairMemoryRecallPort


@dataclass(frozen=True, slots=True)
class ReaderRepairGraphRequest:
    """Immutable input accepted by the Reader Repair Graph application service."""

    run_id: str
    reader_payload: ResearchReaderPayload
    source_format: str = "pdf"
    tenant_id: str | None = None
    user_id: str | None = None
    memory_namespace: str | None = None
    created_at: datetime | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.run_id, str) or not self.run_id.strip():
            raise ValueError("run_id must be a non-blank string")
        if not isinstance(self.reader_payload, ResearchReaderPayload):
            raise TypeError("reader_payload must be ResearchReaderPayload")
        if not isinstance(self.source_format, str) or not self.source_format.strip():
            raise ValueError("source_format must be a non-blank string")
        if self.created_at is not None:
            if self.created_at.tzinfo is None or self.created_at.utcoffset() is None:
                raise ValueError("created_at must be timezone-aware")


@dataclass(frozen=True, slots=True)
class ReaderRepairGraphRunResult:
    request: ReaderRepairGraphRequest
    harness_result: HarnessRunResult

    @property
    def run_id(self) -> str:
        return self.request.run_id

    @property
    def status(self) -> str:
        return self.harness_result.status.value

    @property
    def succeeded(self) -> bool:
        return self.harness_result.succeeded

    @property
    def worker_results(self) -> Mapping[str, Any]:
        return self.harness_result.worker_results


class _ReaderRepairActivityMarker:
    """Exact activity contract marker used by the physical dispatcher.

    Reader Repair never calls the activity implementation directly.  Worker
    invocation is owned by ``HarnessGraphPhysicalActivityExecutor``; the
    marker exists to bind the Graph's activity reference and safety contract.
    """

    capabilities = HarnessActivityCapabilities(stable_idempotency=True)

    def __init__(self, reference: HarnessContractReference) -> None:
        self.activity_contract_id = reference.contract_id
        self.activity_contract_version = reference.version

    def dispatch(self, _request: dict[str, Any]) -> dict[str, Any]:
        raise HarnessValidationError(
            "Reader Repair activities must execute through the physical Graph dispatcher",
            code="reader_repair_activity_direct_dispatch_forbidden",
        )


class _ReaderRepairRunAuthority:
    def __init__(self, context: ReaderRepairRunAuthorityContext) -> None:
        self._context = context

    def resolve(self, *, run_id: str) -> ReaderRepairRunAuthorityContext:
        if run_id != self._context.run_id:
            raise HarnessValidationError(
                "Reader Repair run authority belongs to another run",
                code="reader_repair_run_authority_mismatch",
            )
        return self._context


class _ReaderRepairCommittedOutput:
    def __init__(
        self,
        *,
        event_port: HarnessTransitionPort,
        node_output_resource: HarnessNodeOutputResourcePort,
    ) -> None:
        self._event_port = event_port
        self._resolver = HarnessCommittedNodeOutputInputResolver(
            resource=node_output_resource
        )

    def resolve(
        self,
        *,
        definition: HarnessGraphDefinition,
        run_id: str,
        application,
    ) -> HarnessCommittedNodeOutputReceipt:
        recovery = self._event_port.recover_graph(run_id)
        binding = definition.committed_output_binding(
            READER_REPAIR_COMMITTED_OUTPUT_BINDING_ID
        )
        if binding is None:
            raise HarnessValidationError(
                "Reader Repair Graph lacks its committed-output binding",
                code="reader_repair_committed_output_binding_missing",
            )
        activities = [
            activity
            for activity in recovery.activities
            if activity.run_id == run_id
            and activity.node_id == binding.producer_node_id
        ]
        result_activity_ids = {
            commit.result.activity_id for commit in recovery.activity_result_commits
        }
        completed = [
            activity for activity in activities if activity.activity_id in result_activity_ids
        ]
        if not completed:
            raise EventIncompleteHistoryError(
                "Reader Repair committed application output is not durable"
            )
        producer = max(completed, key=lambda item: (item.attempt, item.activity_id))
        return self._resolver.resolve(
            definition=definition,
            binding_id=READER_REPAIR_COMMITTED_OUTPUT_BINDING_ID,
            producer_activity=producer,
            payload={
                READER_REPAIR_APPLICATION_OUTPUT_KEY: application.to_dict(),
            },
        )


class ReaderRepairGraphApplicationService:
    """Run the exact Reader Repair Graph through Harness-owned control flow."""

    def __init__(
        self,
        *,
        event_port_factory: Callable[[str], HarnessTransitionPort],
        scoped_event_port_factory: Callable[[str, Mapping[str, Any]], HarnessTransitionPort] | None = None,
        node_output_resource: HarnessNodeOutputResourcePort,
        side_effect_store: HarnessSideEffectStorePort,
        memory: ReaderRepairMemoryRecallPort,
        memory_side_effect_handler: HarnessSideEffectPreparationHandler,
        failure_diagnostic_side_effect_handler: HarnessSideEffectHandler,
        candidate_worker: ResearchCandidateWorkerPort,
    ) -> None:
        if not callable(event_port_factory):
            raise TypeError("event_port_factory must be callable")
        if not isinstance(node_output_resource, HarnessNodeOutputResourcePort):
            raise TypeError("node_output_resource must implement HarnessNodeOutputResourcePort")
        if not isinstance(side_effect_store, HarnessSideEffectStorePort):
            raise TypeError("side_effect_store must implement HarnessSideEffectStorePort")
        if not isinstance(memory, ReaderRepairMemoryRecallPort):
            raise TypeError("memory must implement ReaderRepairMemoryRecallPort")
        if not isinstance(memory_side_effect_handler, HarnessSideEffectPreparationHandler):
            raise TypeError(
                "memory_side_effect_handler must support prepare and commit"
            )
        if not isinstance(failure_diagnostic_side_effect_handler, HarnessSideEffectHandler):
            raise TypeError(
                "failure_diagnostic_side_effect_handler must support commit"
            )
        if not isinstance(candidate_worker, ResearchCandidateWorkerPort):
            raise TypeError("candidate_worker must implement ResearchCandidateWorkerPort")
        self._event_port_factory = event_port_factory
        self._scoped_event_port_factory = scoped_event_port_factory
        self._node_output_resource = node_output_resource
        self._side_effect_store = side_effect_store
        self._memory = memory
        self._memory_side_effect_handler = memory_side_effect_handler
        self._failure_handler = failure_diagnostic_side_effect_handler
        self._candidate_worker = candidate_worker
        self._scope_resolver = AskPaperUseCase()

    def repair(self, request: ReaderRepairGraphRequest) -> ReaderRepairGraphRunResult:
        if not isinstance(request, ReaderRepairGraphRequest):
            raise TypeError("request must be ReaderRepairGraphRequest")
        scope = self._scope_resolver.resolve_actor_scope(
            tenant_id=request.tenant_id,
            user_id=request.user_id,
            memory_namespace=request.memory_namespace,
        )
        actor_metadata = scope.to_metadata()
        identity_scope_ref = research_identity_scope_ref(actor_metadata)
        subject_scope_ref = research_subject_scope_ref(
            request.reader_payload.paper.paper_id
        )
        event_port = (
            self._event_port_factory(request.run_id)
            if self._scoped_event_port_factory is None
            else self._scoped_event_port_factory(request.run_id, actor_metadata)
        )
        if not isinstance(event_port, HarnessTransitionPort):
            raise TypeError("event_port_factory must return HarnessTransitionPort")
        created_at = _created_at_for_run(event_port, request.run_id, request.created_at)
        context = ReaderRepairRunAuthorityContext(
            run_id=request.run_id,
            paper_id=request.reader_payload.paper.paper_id,
            created_at=created_at,
            identity_scope_ref=identity_scope_ref,
            subject_scope_ref=subject_scope_ref,
        )
        definition = build_reader_repair_graph_definition()
        function_workers = build_reader_repair_function_worker_implementations(
            memory=self._memory,
            run_authority_resolver=_ReaderRepairRunAuthority(context),
            committed_output_resolver=_ReaderRepairCommittedOutput(
                event_port=event_port,
                node_output_resource=self._node_output_resource,
            ),
        )
        subagent_workers = build_reader_repair_subagent_worker_implementations(
            candidate_worker=self._candidate_worker,
        )
        workers = {**function_workers, **subagent_workers}
        activities = {
            activity.step_id: _ReaderRepairActivityMarker(
                definition.leaf_activity_binding(activity.step_id).activity_ref
            )
            for activity in definition.activities
            if definition.leaf_activity_binding(activity.step_id) is not None
        }
        bundle = build_reader_repair_runtime_binding_bundle(
            worker_implementations=workers,
            activity_implementations=activities,
            memory_side_effect_handler=self._memory_side_effect_handler,
            failure_diagnostic_side_effect_handler=self._failure_handler,
        )
        run_spec = HarnessRunSpec(
            run_id=request.run_id,
            graph=bundle.definition,
            inputs={
                "reader_payload": request.reader_payload.to_dict(),
                "run_id": request.run_id,
                "source_format": request.source_format,
            },
            # The graph has ten serial activities; keep a bounded budget that
            # covers PLAN/EXECUTE/VERIFY for each activity plus one repair
            # round without inheriting the twelve-turn generic default.
            budget=HarnessBudget(
                max_turns=40,
                max_replans=3,
                max_retries_per_step=2,
                max_worker_calls=32,
            ),
            metadata={
                "research_runtime": "reader_repair",
                "paper_id": request.reader_payload.paper.paper_id,
                "graph_terminal_tenant_id": research_event_tenant_id(actor_metadata),
                "tenant_scope_ref": identity_scope_ref,
                "identity_scope_ref": identity_scope_ref,
                "subject_scope_ref": subject_scope_ref,
                **actor_metadata,
            },
            created_at=created_at,
        )
        control_plane = HarnessControlPlane(
            event_port=event_port,
            runtime_binding_authority=bundle.authority,
            gate_registry=bundle.gate_registry,
            side_effect_registry=bundle.side_effect_registry,
            side_effect_store=self._side_effect_store,
            graph_preflight=HarnessGraphPreflight(
                policy=HarnessGraphPreflightPolicy(max_active_nodes=1, max_parallelism=1)
            ),
        )
        compiled_graph = HarnessGraphCompiler().compile(bundle.definition).graph
        executor = HarnessGraphPhysicalActivityExecutor(
            binding_authority=bundle.authority,
            input_resolver=control_plane,
            node_output_resource=self._node_output_resource,
            result_committer=None,
            supervisor=AttemptSupervisor(),
        )
        dispatcher = HarnessGraphPhysicalActivityDispatcher(
            executor=executor,
            graph_resolver=lambda activity: compiled_graph,
            input_resolver=control_plane,
            accept=control_plane.accept_graph_activity_for_execution,
            record_call_marker=control_plane.record_graph_activity_call_marker,
            record_result=control_plane.record_graph_activity_result_event,
            apply_result=control_plane.commit_physical_graph_result,
            capabilities_resolver=lambda activity_ref: bundle.authority.resolve_activity(
                activity_ref,
                required_usage=HarnessActivityUsage.SERIAL,
            ).capabilities,
        )
        control_plane.install_graph_activity_dispatcher(dispatcher)
        recovery = event_port.recover_graph(request.run_id)
        harness_result = (
            control_plane.recover_and_run(run_spec)
            if recovery.state is not None
            else control_plane.run(run_spec)
        )
        return ReaderRepairGraphRunResult(
            request=request,
            harness_result=harness_result,
        )


def _created_at_for_run(
    event_port: HarnessTransitionPort,
    run_id: str,
    requested: datetime | None,
) -> datetime:
    history = event_port.read_history(run_id)
    created = tuple(
        event for event in history if event.event_type is HarnessEventType.RUN_CREATED
    )
    if len(created) > 1:
        raise HarnessValidationError(
            "Reader Repair history contains duplicate RUN_CREATED events",
            code="reader_repair_run_created_event_invalid",
        )
    if created:
        return created[0].occurred_at
    return requested or utc_now()


__all__ = [
    "ReaderRepairGraphApplicationService",
    "ReaderRepairGraphRequest",
    "ReaderRepairGraphRunResult",
]
