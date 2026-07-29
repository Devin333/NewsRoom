from __future__ import annotations

import json
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from business.research.application import AnalyzePaperRequest, AnalyzePaperUseCase
from business.research.application.single_paper_runtime import ResearchSinglePaperRuntime
from business.research.workflows.paper_analysis_workflow import (
    build_paper_analysis_workflow_spec,
)
from framework.events.canonical import checksum_for
from framework.events.runtime.history import DeterministicHistoryRecord
from framework.harness import (
    CountingHarnessSideEffectHandler,
    DeterministicGate,
    DeterministicGateRegistry,
    FakeArtifactPort,
    GateContext,
    GateReference,
    GateRegistration,
    HarnessBudget,
    HarnessCheckpoint,
    HarnessControlPlane,
    HarnessGateResult,
    HarnessRetryPolicy,
    HarnessRoutingRule,
    HarnessRunSpec,
    HarnessSideEffectHandlerBinding,
    HarnessSideEffectIntent,
    HarnessSideEffectRegistry,
    HarnessStepSpec,
    HarnessWorkerResult,
    HarnessWorkflowGraphCompiler,
    HarnessWorkflowSpec,
    InMemoryHarnessEventPort,
    InMemoryHarnessSideEffectStore,
    harness_worker_candidate_ref,
)
from tests.business.research.fakes import (
    FakeGithubRepositoryPort,
    FakeResearchDocumentCompiler,
    FakeResearchLLMWorker,
    FakeResearchRAGRuntime,
    FakeResearchSourceProvider,
)


_FIXTURE = Path("tests/fixtures/harness/graph_migration/current_v1_golden.json")
_FIXED_AT = datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)
_IDENTITY_SCOPE_REF = checksum_for({"tenant_id": "golden-tenant"})
_SUBJECT_SCOPE_REF = checksum_for({"paper_id": "golden-paper"})


class _RoutingGate(DeterministicGate):
    gate_name = "golden_routing"
    gate_version = "1"

    def evaluate(self, context: GateContext) -> HarnessGateResult:
        del context
        return HarnessGateResult(
            gate_name=self.gate_name,
            passed=True,
            details={"score": 0.95},
        )


def test_current_v1_harness_and_research_behavior_matches_golden_fixture() -> None:
    expected = json.loads(_FIXTURE.read_text(encoding="utf-8"))

    assert build_current_v1_golden_snapshot() == expected


def build_current_v1_golden_snapshot() -> dict[str, Any]:
    linear = _linear_run()
    conditional = _conditional_run()
    retry = _retry_run()
    replan = _replan_run()
    repair = _repair_run()
    approval = _approval_run()
    side_effect, side_effect_store, side_effect_handler = _side_effect_run()
    checkpoint = _checkpoint()
    research = _research_result()
    research_workflow = build_paper_analysis_workflow_spec()
    compiled_research = HarnessWorkflowGraphCompiler().compile(research_workflow).graph

    decision_histories = [
        DeterministicHistoryRecord.from_dict(event.deterministic_history)
        for event in linear.events
        if event.event_type.value == "decision_recorded"
    ]
    return {
        "schema": "newsroom.harness-graph-migration-golden/v1",
        "linear_research_workflow": {
            "workflow_checksum": checksum_for(research_workflow.to_dict()),
            "compiled_graph_checksum": compiled_research.checksum,
            "step_ids": list(research_workflow.step_ids),
            "entry_step_id": research_workflow.entry_step_id,
            "route_pairs": [
                [rule.from_step, rule.to_step] for rule in research_workflow.routing_rules
            ],
            "terminal_policy": research_workflow.terminal_side_effect_policy.to_dict(),
        },
        "linear_execution": _run_projection(linear),
        "conditional_route": {
            **_run_projection(conditional),
            "called_steps": sorted(conditional.worker_results),
        },
        "retry": _run_projection(retry),
        "replan": _run_projection(replan),
        "repair": _run_projection(repair),
        "approval_wait": _run_projection(approval),
        "side_effect_publication": {
            **_run_projection(side_effect),
            "handler_calls": side_effect_handler.call_count,
            "decision_writes": side_effect_store.decision_write_count,
            "outcome_writes": side_effect_store.outcome_write_count,
            "outcomes": {
                step_id: {
                    "status": outcome.status.value,
                    "disposition": outcome.disposition.value,
                    "handler_ref": str(outcome.handler),
                }
                for step_id, outcome in sorted(side_effect.side_effect_outcomes.items())
            },
            "durable_reference_keys": sorted(
                key
                for step in side_effect.state.step_states
                for key in step.metadata
                if key.startswith("side_effect_")
            ),
        },
        "durable_history": {
            "schema": decision_histories[0].schema,
            "decision_count": len(decision_histories),
            "command_ordinals": [history.commands[0].ordinal for history in decision_histories],
            "one_command_per_decision": all(
                len(history.commands) == 1 for history in decision_histories
            ),
        },
        "checkpoint": {
            "checksum": checkpoint.checksum,
            "last_event_id": checkpoint.last_event_id,
            "status": checkpoint.state.status.value,
            "current_step_id": checkpoint.state.current_step_id,
            "step_statuses": {
                step.step_id: step.status.value for step in checkpoint.state.step_states
            },
        },
        "final_business_result": research,
    }


def _linear_run():
    workflow = HarnessWorkflowSpec(
        workflow_id="golden-linear",
        steps=(
            HarnessStepSpec("collect", "llm", output_key="evidence"),
            HarnessStepSpec("report", "llm", input_keys=("evidence",), output_key="report"),
        ),
        entry_step_id="collect",
    )
    return HarnessControlPlane(
        event_port=InMemoryHarnessEventPort(),
        worker_registry={
            "collect": lambda task: HarnessWorkerResult(
                "succeeded", output={"evidence": ["claim-1"]}
            ),
            "report": lambda task: HarnessWorkerResult(
                "succeeded", output={"report": "grounded"}
            ),
        },
    ).run(HarnessRunSpec("golden-linear-run", workflow, created_at=_FIXED_AT))


def _conditional_run():
    workflow = HarnessWorkflowSpec(
        workflow_id="golden-conditional",
        steps=(
            HarnessStepSpec("classify", "llm", quality_gate="golden_routing@1"),
            HarnessStepSpec("normal", "script"),
            HarnessStepSpec("repair", "script"),
        ),
        entry_step_id="classify",
        routing_rules=(
            HarnessRoutingRule(
                "classify",
                "repair",
                kind="on_verdict",
                condition={"passed": True, "min_score": 0.8},
            ),
        ),
    )
    registry = DeterministicGateRegistry(
        (
            GateRegistration(
                reference=GateReference.parse("golden_routing@1"),
                gate=_RoutingGate(),
            ),
        )
    )
    return HarnessControlPlane(
        event_port=InMemoryHarnessEventPort(),
        worker_registry={
            "classify": lambda task: HarnessWorkerResult("succeeded", output={"kind": "repair"}),
            "normal": lambda task: HarnessWorkerResult("succeeded", output={"normal": True}),
            "repair": lambda task: HarnessWorkerResult("succeeded", output={"fixed": True}),
        },
        gate_registry=registry,
    ).run(HarnessRunSpec("golden-conditional-run", workflow, created_at=_FIXED_AT))


def _retry_run():
    workflow = HarnessWorkflowSpec(
        workflow_id="golden-retry",
        steps=(
            HarnessStepSpec(
                "call",
                "llm",
                retry_policy=HarnessRetryPolicy(max_attempts=2),
            ),
        ),
        entry_step_id="call",
    )
    return HarnessControlPlane(
        event_port=InMemoryHarnessEventPort(),
        worker_registry={
            "call": (
                HarnessWorkerResult("failed", error="transient"),
                HarnessWorkerResult("succeeded", output={"value": "ok"}),
            )
        },
    ).run(
        HarnessRunSpec(
            "golden-retry-run",
            workflow,
            created_at=_FIXED_AT,
            budget=HarnessBudget(20, 0, 2, 5),
        )
    )


def _replan_run():
    workflow = HarnessWorkflowSpec(
        workflow_id="golden-replan",
        steps=(
            HarnessStepSpec(
                "draft",
                "llm",
                metadata={"output_schema": {"required": ["title"]}},
            ),
        ),
        entry_step_id="draft",
    )
    return HarnessControlPlane(
        event_port=InMemoryHarnessEventPort(),
        worker_registry={"draft": lambda task: HarnessWorkerResult("succeeded", output={"body": "x"})},
    ).run(
        HarnessRunSpec(
            "golden-replan-run",
            workflow,
            created_at=_FIXED_AT,
            budget=HarnessBudget(20, 1, 0, 5),
        )
    )


def _repair_run():
    workflow = HarnessWorkflowSpec(
        workflow_id="golden-repair",
        steps=(
            HarnessStepSpec(
                "draft",
                "llm",
                retry_policy=HarnessRetryPolicy(repair_step_id="repair"),
                metadata={"output_schema": {"required": ["title"]}},
            ),
            HarnessStepSpec("repair", "script"),
        ),
        entry_step_id="draft",
    )
    return HarnessControlPlane(
        event_port=InMemoryHarnessEventPort(),
        worker_registry={
            "draft": lambda task: HarnessWorkerResult("succeeded", output={"body": "x"}),
            "repair": lambda task: HarnessWorkerResult("succeeded", output={"title": "fixed"}),
        },
    ).run(HarnessRunSpec("golden-repair-run", workflow, created_at=_FIXED_AT))


def _approval_run():
    workflow = HarnessWorkflowSpec(
        workflow_id="golden-approval",
        steps=(HarnessStepSpec("publish", "artifact", metadata={"approval_required": True}),),
        entry_step_id="publish",
    )
    return HarnessControlPlane(
        event_port=InMemoryHarnessEventPort(),
        worker_registry={"publish": lambda task: HarnessWorkerResult("succeeded", output={"candidate": "x"})},
    ).run(HarnessRunSpec("golden-approval-run", workflow, created_at=_FIXED_AT))


def _side_effect_run():
    store = InMemoryHarnessSideEffectStore()
    handler = CountingHarnessSideEffectHandler(store)
    workflow = HarnessWorkflowSpec(
        workflow_id="golden-side-effect",
        steps=(
            HarnessStepSpec(
                "publish",
                "artifact",
                output_key="candidate",
                side_effect_handler="golden.publish@1",
            ),
        ),
        entry_step_id="publish",
    )

    def worker(task: dict[str, Any]) -> HarnessWorkerResult:
        output = {"candidate": "report"}
        candidate = {
            "status": "succeeded",
            "output": output,
            "artifacts": ["candidate://golden/report"],
            "diagnostics": {},
            "metrics": {},
            "error": None,
        }
        return HarnessWorkerResult(
            "succeeded",
            output=output,
            artifacts=("candidate://golden/report",),
            effect_intent=HarnessSideEffectIntent(
                effect_id="golden-effect",
                kind="artifact",
                run_id=task["run_id"],
                origin="worker",
                atomic_group="golden-run",
                identity_scope_ref=_IDENTITY_SCOPE_REF,
                subject_scope_ref=_SUBJECT_SCOPE_REF,
                attempt=task["harness_activity"]["attempt"],
                step_id=task["step_id"],
                worker_result_ref=harness_worker_candidate_ref(candidate),
                candidate_checksum=checksum_for(output),
                handler="golden.publish@1",
                payload={"member": "report"},
                candidate_refs=("candidate://golden/report",),
            ),
        )

    result = HarnessControlPlane(
        event_port=InMemoryHarnessEventPort(),
        worker_registry={"publish": worker},
        side_effect_registry=HarnessSideEffectRegistry(
            (HarnessSideEffectHandlerBinding("golden.publish@1", "artifact", handler),)
        ),
        side_effect_store=store,
    ).run(
        HarnessRunSpec(
            "golden-side-effect-run",
            workflow,
            created_at=_FIXED_AT,
            metadata={
                "identity_scope_ref": _IDENTITY_SCOPE_REF,
                "subject_scope_ref": _SUBJECT_SCOPE_REF,
            },
        )
    )
    return result, store, handler


def _checkpoint() -> HarnessCheckpoint:
    workflow = HarnessWorkflowSpec(
        workflow_id="golden-checkpoint",
        steps=(HarnessStepSpec("collect", "script"),),
        entry_step_id="collect",
    )
    run_spec = HarnessRunSpec("golden-checkpoint-run", workflow, created_at=_FIXED_AT)
    from framework.harness import HarnessState

    return HarnessCheckpoint(
        checkpoint_id="golden-checkpoint-1",
        run_id=run_spec.run_id,
        state=HarnessState.initial(run_spec),
        last_event_id="event-golden-1",
        created_at=_FIXED_AT,
    )


def _research_result() -> dict[str, Any]:
    runtime = ResearchSinglePaperRuntime(
        source_provider=FakeResearchSourceProvider(),
        document_compiler=FakeResearchDocumentCompiler(),
        llm_worker=FakeResearchLLMWorker(),
        github_repository=FakeGithubRepositoryPort(),
        rag_runtime=FakeResearchRAGRuntime(),
        artifact_port=FakeArtifactPort(),
        event_port_factory=lambda run_id: InMemoryHarnessEventPort(),
    )
    result = AnalyzePaperUseCase(runtime).analyze(
        AnalyzePaperRequest(
            run_id="golden-research-run",
            paper_id="paper-harness-001",
            source_ref="https://arxiv.org/abs/2606.00123",
            user_id="golden-user",
        )
    )
    return {
        "run_id": result.run_id,
        "status": result.status,
        "succeeded": result.succeeded,
        "analysis_present": result.analysis is not None,
        "quality": {
            "passed": result.quality.passed,
            "score": result.quality.score,
        },
        "paper_card_present": result.paper_card is not None,
        "reader_payload_present": result.reader_payload is not None,
        "rag_context_present": result.rag_context is not None,
        "artifact_types": sorted(result.artifact_refs),
        "worker_steps": sorted(result.diagnostics["worker_results"]),
        "trace_event_types": sorted({event.event_type.value for event in result.trace.events}),
    }


def _run_projection(result) -> dict[str, Any]:
    return {
        "status": result.state.status.value,
        "current_step_id": result.state.current_step_id,
        "decisions": [
            ":".join(
                (
                    decision.decision_type.value,
                    decision.step_id or "-",
                    decision.target_step_id or "-",
                )
            )
            for decision in result.decisions
        ],
        "event_type_counts": dict(
            sorted(Counter(event.event_type.value for event in result.events).items())
        ),
        "phase_sequence": [
            f"{event.step_id}:{event.payload['phase']}:{event.payload['boundary']}"
            for event in result.events
            if event.event_type.value == "phase_recorded"
        ],
        "step_states": {
            step.step_id: {
                "status": step.status.value,
                "attempts": step.attempts,
                "replans": step.replans,
            }
            for step in result.state.step_states
        },
        "counters": {
            "turns": result.state.turn_count,
            "replans": result.state.replan_count,
            "worker_calls": result.state.worker_call_count,
        },
        "terminal_reason": result.state.metadata.get("terminal_reason"),
        "worker_steps": sorted(result.worker_results),
    }


__all__ = ["build_current_v1_golden_snapshot"]
