from __future__ import annotations

from collections.abc import Callable
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest

from business.research.application import (
    AnalyzePaperRequest,
    AnalyzePaperUseCase,
    ResearchDynamicTaskPlanUnavailableError,
)
from business.research.application.single_paper_runtime import (
    ResearchSinglePaperRuntime,
)
from business.research.workflows import (
    RESEARCH_DYNAMIC_CAPABILITIES,
    RESEARCH_DYNAMIC_SUBAGENT_IDS,
    ResearchAnalysisPlanCandidateBuilder,
    ResearchAnalysisTaskPlanStageWorker,
    build_dynamic_paper_analysis_workflow_spec,
    build_research_analysis_capability_registry,
    build_research_analysis_task_gate_registry,
    build_research_analysis_task_plan_policy,
    build_paper_analysis_gate_registry,
)
from framework.harness import (
    ContextEnvelope,
    FakeArtifactPort,
    HarnessBudget,
    HarnessBudgetSnapshot,
    HarnessState,
    HarnessWorkerResult,
    InMemoryHarnessEventPort,
    InMemoryTaskPlanStore,
    FakeSubAgentTranscriptStore,
    ResolvedSubAgentTaskAdapter,
    SubAgentRuntime,
    SubAgentStatus,
    TaskLifecycle,
    TaskPlanResultVerifier,
    TaskPlanReplayReducer,
    subagent_attempt_evidence,
)
from framework.harness.control_plane.gates import GateContext
from framework.harness.graph import HarnessWorkerType
from framework.harness.workflow import HarnessWorkflowGraphCompiler
from framework.harness.graph.bindings import HarnessWorkerBinding
from framework.harness.graph.model import (
    HarnessContractKind,
    HarnessContractReference,
)
from infrastructure.storage.harness import FilesystemSubAgentTranscriptStore
from interfaces.services.research_service import (
    InMemoryResearchRunStore,
    ResearchAnalyzeInput,
    ResearchApplicationService,
    ResearchServiceError,
)
from tests.business.research.fakes import (
    FIXED_NOW,
    FakeGithubRepositoryPort,
    FakeResearchDocumentCompiler,
    FakeResearchLLMWorker,
    FakeResearchRAGRuntime,
    FakeResearchSourceProvider,
)


class _WorkspaceAnalysisSubAgent:
    worker_version = "1"
    worker_type = HarnessWorkerType.SUBAGENT

    def __init__(
        self,
        capability: str,
        *,
        dependencies: Any,
        workspace: Any,
    ) -> None:
        self.worker_id = capability
        self._dependencies = dependencies
        self._workspace = workspace
        self.calls: list[dict[str, Any]] = []

    def execute(self, task: dict[str, Any]) -> HarnessWorkerResult:
        self.calls.append(task)
        worker = {
            "research.analysis.structure": (
                ResearchSinglePaperRuntime._analyze_structure
            ),
            "research.analysis.contribution": (
                ResearchSinglePaperRuntime._analyze_contribution
            ),
            "research.analysis.experiments": (
                ResearchSinglePaperRuntime._analyze_experiments
            ),
        }[self.worker_id]
        return worker(self._dependencies, task, self._workspace)


class _PlanOutlineWorker:
    def __init__(
        self,
        source: Any,
        transform: Callable[[dict[str, Any]], dict[str, Any]] | None,
    ) -> None:
        self._source = source
        self._transform = transform
        self.calls = 0

    def generate_candidate(self, *, task: str, payload: dict[str, Any]):
        assert task == "candidate_task_plan"
        self.calls += 1
        outline = self._source.generate_candidate(task=task, payload=payload)
        return outline if self._transform is None else self._transform(outline)


class _DynamicTaskPlanFactory:
    def __init__(
        self,
        *,
        outline_transform: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
        transcript_root: Path | None = None,
        crash_after_receipt_once: bool = False,
    ) -> None:
        self.outline_transform = outline_transform
        self.transcript_root = transcript_root
        self.crash_after_receipt_once = crash_after_receipt_once
        self._crashed_after_receipt = False
        self.stores: list[InMemoryTaskPlanStore] = []
        self.transcript_stores: list[Any] = []
        self.outline_workers: list[_PlanOutlineWorker] = []
        self.subagent_runtimes: list[SubAgentRuntime] = []
        self.subagent_workers: list[dict[str, _WorkspaceAnalysisSubAgent]] = []
        self.stage_workers: list[ResearchAnalysisTaskPlanStageWorker] = []

    def __call__(self, *, workspace: Any, dependencies: Any):
        policy = build_research_analysis_task_plan_policy()
        workers = {
            capability: _WorkspaceAnalysisSubAgent(
                capability,
                dependencies=dependencies,
                workspace=workspace,
            )
            for capability in RESEARCH_DYNAMIC_CAPABILITIES
        }
        bindings = {
            capability: HarnessWorkerBinding(
                HarnessContractReference(
                    HarnessContractKind.WORKER,
                    capability,
                    "1",
                ),
                HarnessWorkerType.SUBAGENT,
                worker,
            )
            for capability, worker in workers.items()
        }
        registry = build_research_analysis_capability_registry(bindings)
        transcript_store = (
            FilesystemSubAgentTranscriptStore(self.transcript_root)
            if self.transcript_root is not None
            else FakeSubAgentTranscriptStore()
        )
        runtime = SubAgentRuntime(
            workers={
                RESEARCH_DYNAMIC_SUBAGENT_IDS[capability]: worker
                for capability, worker in workers.items()
            },
            transcript_store=transcript_store,
        )
        adapter = ResolvedSubAgentTaskAdapter(runtime)
        store = InMemoryTaskPlanStore()
        outline_worker = _PlanOutlineWorker(
            dependencies.llm_worker,
            self.outline_transform,
        )
        context_pack = ContextEnvelope(
            envelope_id=f"research-task-plan-context:{workspace.request.run_id}",
            run_id=workspace.request.run_id,
            workflow_id="research.paper_analysis.dynamic",
            step_id="dynamic_analysis_stage",
            phase="EXECUTE",
            worker_id="research.task-plan",
            worker_type=HarnessWorkerType.TASK_PLAN.value,
            dynamic_tail={
                "input_refs": ["document", "evidence_pack"],
                "raw_parent_messages_included": False,
            },
        )
        budget = HarnessBudgetSnapshot.from_budget(HarnessBudget.safe_default())

        def gate_context(task_request):
            from business.research.application.single_paper_runtime import (
                build_research_harness_run_spec,
            )

            run_spec = build_research_harness_run_spec(
                workspace.request,
                created_at=FIXED_NOW,
            )
            base_state = HarnessState.initial(run_spec)
            state = HarnessState(
                run_spec=base_state.run_spec,
                status=base_state.status,
                step_states=base_state.step_states,
                current_step_id="dynamic_analysis_stage",
                metadata={
                    "outputs": {
                        "evidence_pack": {
                            "evidence_pack": workspace.evidence_pack.to_dict()
                        }
                    }
                },
                updated_at=base_state.updated_at,
            )
            step_spec = next(
                step
                for step in run_spec.workflow.steps
                if step.step_id == "dynamic_analysis_stage"
            )
            step_state = next(
                item
                for item in state.step_states
                if item.step_id == "dynamic_analysis_stage"
            )
            return GateContext(
                state=state,
                step_spec=step_spec,
                step_state=step_state,
                worker_result=task_request.worker_result,
                budget=budget,
            )

        task_gate_registry = build_research_analysis_task_gate_registry(
            build_paper_analysis_gate_registry(),
            context_factory=gate_context,
        )

        def resolve_task(task_instance):
            plan = store.plan(
                task_instance.run_id,
                task_instance.stage_id,
                task_instance.plan_version,
            )
            assert plan is not None
            resolved_task = next(
                task
                for task in plan.tasks
                if task.task_id == task_instance.task_id
            )
            return plan, resolved_task

        def invoke_child(resolved_binding, task_instance, *, recover: bool = False):
            plan, resolved_task = resolve_task(task_instance)
            method = adapter.recover if recover else adapter.invoke
            return method(
                resolved_task=resolved_task,
                binding=resolved_binding,
                task_instance_id=task_instance.task_instance_id,
                parent_run_id=task_instance.run_id,
                workflow_id=plan.workflow_id,
                stage_id=task_instance.stage_id,
                context_pack=context_pack,
                budget_snapshot=budget,
                attempt=task_instance.attempt,
                observed_at=plan.accepted_at,
            )

        def worker_result(subagent_result, *, recovered: bool = False):
            if subagent_result is None:
                return None
            succeeded = subagent_result.status is SubAgentStatus.SUCCEEDED
            return HarnessWorkerResult(
                status="succeeded" if succeeded else "failed",
                output=subagent_result.output,
                artifacts=subagent_result.artifact_refs,
                diagnostics={
                    "subagent_id": subagent_result.subagent_id,
                    "recovered": recovered,
                },
                evidence=(subagent_attempt_evidence(subagent_result.transcript_receipt),)
                if subagent_result.transcript_receipt is not None
                else (),
                error=None if succeeded else "Research analysis subagent gate failed",
            )

        def execute(resolved_binding, task_instance):
            result = worker_result(invoke_child(resolved_binding, task_instance))
            assert result is not None
            if (
                self.crash_after_receipt_once
                and not self._crashed_after_receipt
            ):
                self._crashed_after_receipt = True
                raise RuntimeError("injected post-receipt crash")
            return result

        def recover(resolved_binding, task_instance):
            return worker_result(
                invoke_child(resolved_binding, task_instance, recover=True),
                recovered=True,
            )

        graph = HarnessWorkflowGraphCompiler().compile(
            build_dynamic_paper_analysis_workflow_spec()
        ).graph
        stage_worker = ResearchAnalysisTaskPlanStageWorker(
            graph_checksum=graph.checksum,
            accepted_at="2026-08-01T00:00:00Z",
            candidate_builder=ResearchAnalysisPlanCandidateBuilder(outline_worker),
            capability_registry=registry,
            store=store,
            worker_executor=execute,
            worker_result_recovery=recover,
            result_verifier=TaskPlanResultVerifier(
                task_gate_registry,
                transcript_store=transcript_store,
            ),
            policy=policy,
            allow_test_store=True,
        )
        self.stores.append(store)
        self.transcript_stores.append(transcript_store)
        self.outline_workers.append(outline_worker)
        self.subagent_runtimes.append(runtime)
        self.subagent_workers.append(workers)
        self.stage_workers.append(stage_worker)
        return stage_worker


def test_dynamic_task_plan_fake_llm_and_subagents_publish_through_fixed_path() -> None:
    factory = _DynamicTaskPlanFactory()
    artifact_port = FakeArtifactPort()
    result = _analyze(
        "dynamic-task-plan-success",
        dynamic=True,
        dynamic_factory=factory,
        artifact_port=artifact_port,
    )

    assert result.succeeded is True
    assert factory.outline_workers[0].calls == 1
    assert all(
        len(worker.calls) == 1 for worker in factory.subagent_workers[0].values()
    )
    store_events = factory.stores[0].read_events(
        result.run_id,
        "dynamic_analysis_stage",
    )
    event_types = [event.event_type for event in store_events]
    assert event_types[0:2] == ["PLAN_CANDIDATE_BUILT", "PLAN_ACCEPTED"]
    assert event_types[-2:] == ["STAGE_OUTPUT_AGGREGATED", "TASK_PLAN_VERIFIED"]
    experiment_dispatch = next(
        event.sequence
        for event in store_events
        if event.event_type == "TASK_DISPATCHED"
        and event.task_id == "analyze-experiments"
    )
    structure_result = next(
        event.sequence
        for event in store_events
        if event.event_type == "TASK_RESULT_ACCEPTED"
        and event.task_id == "analyze-structure"
    )
    assert structure_result < experiment_dispatch
    assert {
        "research-analysis",
        "research-quality-result",
        "research-reader-payload",
        "research-paper-card",
        "harness-trace",
        "harness-transcript",
    }.issubset(result.artifact_refs)
    assert result.diagnostics["worker_results"]["publish_artifacts"]["status"] == (
        "succeeded"
    )


def test_missing_dynamic_role_stops_before_subagent_and_publication() -> None:
    def remove_experiments(outline: dict[str, Any]) -> dict[str, Any]:
        result = deepcopy(outline)
        result["tasks"] = [
            task
            for task in result["tasks"]
            if task["worker_capability"] != "research.analysis.experiments"
        ]
        return result

    factory = _DynamicTaskPlanFactory(outline_transform=remove_experiments)
    result = _analyze(
        "dynamic-task-plan-missing-role",
        dynamic=True,
        dynamic_factory=factory,
    )

    assert result.succeeded is False
    assert result.artifact_refs == {}
    assert all(
        worker.calls == [] for worker in factory.subagent_workers[0].values()
    )
    assert set(result.diagnostics["worker_results"]) == {
        "load_paper_source",
        "compile_document",
        "run_research_rag",
        "build_evidence_pack",
        "dynamic_analysis_stage",
    }
    assert "PLAN_VALIDATION_FAILED" in {
        event.event_type
        for event in factory.stores[0].read_events(
            result.run_id,
            "dynamic_analysis_stage",
        )
    }


def test_dynamic_claim_gate_failure_blocks_quality_reader_and_publication() -> None:
    factory = _DynamicTaskPlanFactory()
    result = _analyze(
        "dynamic-task-plan-gate-failure",
        dynamic=True,
        dynamic_factory=factory,
        llm_worker=FakeResearchLLMWorker(missing_evidence=True),
    )

    assert result.succeeded is False
    assert result.artifact_refs == {}
    worker_results = result.diagnostics["worker_results"]
    assert worker_results["dynamic_analysis_stage"]["status"] == "succeeded"
    assert worker_results["verify_claims"]["status"] == "succeeded"
    assert "quality_gate" not in worker_results
    assert "build_reader_payload" not in worker_results
    assert "build_paper_card" not in worker_results
    assert "publish_artifacts" not in worker_results
    assert any(
        failure["details"]["harness_gate"]["reference"] == "ClaimEvidenceGate@1"
        for failure in result.diagnostics["gate_failures"]
    )


def test_static_and_dynamic_public_result_and_artifact_contracts_match() -> None:
    static = _analyze("static-parity", dynamic=False)
    dynamic = _analyze(
        "dynamic-parity",
        dynamic=True,
        dynamic_factory=_DynamicTaskPlanFactory(),
    )

    assert static.succeeded is dynamic.succeeded is True
    assert set(static.to_dict()) == set(dynamic.to_dict())
    assert set(static.artifact_refs) == set(dynamic.artifact_refs)
    assert static.quality.passed is dynamic.quality.passed is True
    assert static.analysis is not None and dynamic.analysis is not None
    assert static.analysis.model_dump(exclude={"analysis_id"}) == (
        dynamic.analysis.model_dump(exclude={"analysis_id"})
    )


def test_dynamic_replay_uses_recorded_outer_result_without_live_plan_or_subagents() -> None:
    event_port = InMemoryHarnessEventPort()
    artifact_port = FakeArtifactPort()
    factory = _DynamicTaskPlanFactory()
    runtime = _runtime(
        dynamic_factory=factory,
        artifact_port=artifact_port,
        event_port=event_port,
    )
    request = AnalyzePaperRequest(
        run_id="dynamic-task-plan-replay",
        paper_id="paper-harness-001",
        source_ref="https://arxiv.org/abs/2606.00123",
        user_id="user-1",
        options={"dynamic_analysis": True},
    )

    first = AnalyzePaperUseCase(runtime).analyze(request)
    first_outline_calls = factory.outline_workers[0].calls
    first_subagent_calls = {
        key: len(value.calls) for key, value in factory.subagent_workers[0].items()
    }
    second = AnalyzePaperUseCase(runtime).analyze(request)

    assert first.succeeded is second.succeeded is True
    assert first.to_dict()["analysis"] == second.to_dict()["analysis"]
    assert first.to_dict()["artifact_refs"] == second.to_dict()["artifact_refs"]
    assert first_outline_calls == 1
    assert first_subagent_calls == {
        key: len(value.calls) for key, value in factory.subagent_workers[0].items()
    }
    assert len(factory.outline_workers) == 2
    assert factory.outline_workers[1].calls == 0
    assert all(
        worker.calls == [] for worker in factory.subagent_workers[1].values()
    )


def test_dynamic_task_plan_filesystem_transcripts_reopen_and_replay_offline(
    tmp_path: Path,
) -> None:
    transcript_root = tmp_path / "artifacts"
    factory = _DynamicTaskPlanFactory(transcript_root=transcript_root)
    result = _analyze(
        "dynamic-durable-lineage",
        dynamic=True,
        dynamic_factory=factory,
    )

    assert result.succeeded is True
    store = factory.stores[0]
    plan = store.plan(result.run_id, "dynamic_analysis_stage")
    assert plan is not None
    records = store.results_for(result.run_id, plan.stage_id, plan.plan_id, plan.version)
    assert len(records) == 3
    reopened = FilesystemSubAgentTranscriptStore(transcript_root)
    for record in records:
        assert record.transcript_ref is not None
        assert record.subagent_output_ref is not None
        transcript = reopened.read(record.transcript_ref)
        output = reopened.read_output(record.subagent_output_ref)
        receipt = reopened.find_by_identity(transcript.identity)
        assert receipt is not None
        assert reopened.verify(receipt) == receipt
        assert receipt.transcript_checksum == record.transcript_checksum
        assert receipt.output_checksum == record.subagent_output_checksum
        assert output.identity == transcript.identity
        assert output.status == "succeeded"

    outline_calls = factory.outline_workers[0].calls
    subagent_calls = {
        capability: len(worker.calls)
        for capability, worker in factory.subagent_workers[0].items()
    }
    replay = TaskPlanReplayReducer(reopened).replay(
        (plan,),
        store.read_events(result.run_id, plan.stage_id),
        results=records,
    )
    assert replay.projection.tasks
    assert all(
        task.status is TaskLifecycle.SUCCEEDED
        for task in replay.projection.tasks
    )
    assert factory.outline_workers[0].calls == outline_calls
    assert {
        capability: len(worker.calls)
        for capability, worker in factory.subagent_workers[0].items()
    } == subagent_calls


def test_dynamic_task_plan_recovers_post_receipt_crash_without_duplicate_worker(
    tmp_path: Path,
) -> None:
    factory = _DynamicTaskPlanFactory(
        transcript_root=tmp_path / "artifacts",
        crash_after_receipt_once=True,
    )
    artifact_port = FakeArtifactPort()
    runtime = _runtime(
        dynamic_factory=factory,
        artifact_port=artifact_port,
    )
    request = AnalyzePaperRequest(
        run_id="dynamic-post-receipt-crash",
        paper_id="paper-harness-001",
        source_ref="https://arxiv.org/abs/2606.00123",
        user_id="user-1",
        options={"dynamic_analysis": True},
    )

    first = AnalyzePaperUseCase(runtime).analyze(request)

    assert first.succeeded is False
    assert first.artifact_refs == {}
    first_workers = factory.subagent_workers[0]
    first_counts = {
        capability: len(worker.calls)
        for capability, worker in first_workers.items()
    }
    assert sum(first_counts.values()) == 1
    store = factory.stores[0]
    plan = store.plan(request.run_id, "dynamic_analysis_stage")
    assert plan is not None
    projection = store.load_projection(request.run_id, plan.stage_id)
    assert sum(
        state.status in {TaskLifecycle.DISPATCHED, TaskLifecycle.RUNNING}
        for state in projection.tasks
    ) == 1
    assert sum(state.status is TaskLifecycle.PENDING for state in projection.tasks) == 2

    resumed = factory.stage_workers[0].run(
        {
            "run_id": request.run_id,
            "step_id": "dynamic_analysis_stage",
            "worker_type": HarnessWorkerType.TASK_PLAN.value,
            "inputs": {
                "document": {},
                "evidence_pack": {},
            },
        }
    )

    assert resumed.status.value == "succeeded"
    assert all(len(worker.calls) == 1 for worker in first_workers.values())
    records = store.results_for(request.run_id, plan.stage_id, plan.plan_id, plan.version)
    assert len(records) == 3
    assert all(record.transcript_ref for record in records)
    assert all(record.subagent_output_ref for record in records)


def test_production_shaped_stage_worker_rejects_in_memory_store_by_default() -> None:
    policy = build_research_analysis_task_plan_policy()

    with pytest.raises(Exception) as exc_info:
        ResearchAnalysisTaskPlanStageWorker(
            graph_checksum="sha256:" + "1" * 64,
            accepted_at="2026-08-01T00:00:00Z",
            candidate_builder=ResearchAnalysisPlanCandidateBuilder(
                FakeResearchLLMWorker()
            ),
            capability_registry=build_research_analysis_capability_registry(
                _dummy_bindings()
            ),
            store=InMemoryTaskPlanStore(),
            worker_executor=lambda *_args: None,
            result_verifier=TaskPlanResultVerifier(),
            policy=policy,
        )
    assert getattr(exc_info.value, "code", None) == (
        "research_task_plan_durable_store_required"
    )


def test_missing_dynamic_production_composition_returns_sanitized_unavailable() -> None:
    runtime = _runtime(dynamic_factory=None)
    service = ResearchApplicationService(
        analyze_use_case=AnalyzePaperUseCase(runtime),
        run_store=InMemoryResearchRunStore(),
    )

    with pytest.raises(ResearchDynamicTaskPlanUnavailableError):
        AnalyzePaperUseCase(runtime).analyze(
            AnalyzePaperRequest(
                run_id="dynamic-unavailable-direct",
                paper_id="paper-harness-001",
                source_ref="https://arxiv.org/abs/2606.00123",
                options={"dynamic_analysis": True},
            )
        )

    with pytest.raises(ResearchServiceError) as exc_info:
        service.analyze_paper(
            ResearchAnalyzeInput(
                run_id="dynamic-unavailable-service",
                paper_id="paper-harness-001",
                source_url="https://arxiv.org/abs/2606.00123",
                options={"dynamic_analysis": True},
            )
        )
    error = exc_info.value
    assert error.code == "research_runtime_unavailable"
    assert error.status_code == 503
    assert error.details == {
        "capabilities": [
            "research.task_plan.builder",
            "research.task_plan.worker_bindings",
            "research.task_plan.store",
        ],
        "remediation": {
            "code": "restore_research_runtime_capability",
            "message": "Restore the named Research capability and retry the request.",
        },
    }


def _analyze(
    run_id: str,
    *,
    dynamic: bool,
    dynamic_factory: _DynamicTaskPlanFactory | None = None,
    artifact_port: FakeArtifactPort | None = None,
    llm_worker: Any | None = None,
):
    runtime = _runtime(
        dynamic_factory=dynamic_factory,
        artifact_port=artifact_port,
        llm_worker=llm_worker,
    )
    return AnalyzePaperUseCase(runtime).analyze(
        AnalyzePaperRequest(
            run_id=run_id,
            paper_id="paper-harness-001",
            source_ref="https://arxiv.org/abs/2606.00123",
            user_id="user-1",
            options={"dynamic_analysis": True} if dynamic else {},
        )
    )


def _runtime(
    *,
    dynamic_factory: _DynamicTaskPlanFactory | None = None,
    artifact_port: FakeArtifactPort | None = None,
    llm_worker: Any | None = None,
    event_port: InMemoryHarnessEventPort | None = None,
) -> ResearchSinglePaperRuntime:
    return ResearchSinglePaperRuntime(
        source_provider=FakeResearchSourceProvider(),
        document_compiler=FakeResearchDocumentCompiler(),
        llm_worker=llm_worker or FakeResearchLLMWorker(),
        github_repository=FakeGithubRepositoryPort(),
        rag_runtime=FakeResearchRAGRuntime(),
        artifact_port=artifact_port or FakeArtifactPort(),
        event_port_factory=lambda _run_id: event_port or InMemoryHarnessEventPort(),
        dynamic_task_plan_runner_factory=dynamic_factory,
    )


def _dummy_bindings() -> dict[str, HarnessWorkerBinding]:
    class _Worker:
        worker_version = "1"
        worker_type = HarnessWorkerType.SUBAGENT

        def __init__(self, capability: str) -> None:
            self.worker_id = capability

        def execute(self, _task):
            return HarnessWorkerResult(status="succeeded")

    return {
        capability: HarnessWorkerBinding(
            HarnessContractReference(
                HarnessContractKind.WORKER,
                capability,
                "1",
            ),
            HarnessWorkerType.SUBAGENT,
            _Worker(capability),
        )
        for capability in RESEARCH_DYNAMIC_CAPABILITIES
    }
