from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from business.research.application import AnalyzePaperRequest, AnalyzePaperUseCase
from business.research.application.single_paper_runtime import (
    ResearchSinglePaperRuntime,
)
from business.research.workflows.paper_analysis_workflow import (
    build_paper_analysis_workflow_spec,
)
from framework.events.canonical import checksum_for
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
    HarnessGraphDecision,
    HarnessGraphDecisionType,
    HarnessRetryPolicy,
    HarnessRunSpec,
    HarnessSideEffectHandlerBinding,
    HarnessSideEffectIntent,
    HarnessSideEffectRegistry,
    HarnessStepSpec,
    HarnessWorkerResult,
    InMemoryHarnessEventPort,
    InMemoryHarnessSideEffectStore,
    harness_worker_candidate_ref,
)
from framework.harness.workflow.compiler import HarnessWorkflowGraphCompiler
from framework.harness.workflow.spec import HarnessRoutingRule, HarnessWorkflowSpec
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
_RUN_FIXTURE_NAMES = (
    "linear_execution",
    "conditional_route",
    "retry",
    "replan",
    "repair",
    "approval_wait",
    "side_effect_publication",
)
_EXPECTED_OUTPUTS = {
    "linear_execution": {
        "collect": {
            "status": "succeeded",
            "output": {"evidence": ["claim-1"]},
            "error": None,
        },
        "report": {
            "status": "succeeded",
            "output": {"report": "grounded"},
            "error": None,
        },
    },
    "conditional_route": {
        "classify": {
            "status": "succeeded",
            "output": {"kind": "repair"},
            "error": None,
        },
        "repair": {"status": "succeeded", "output": {"fixed": True}, "error": None},
    },
    "retry": {
        "call": {"status": "succeeded", "output": {"value": "ok"}, "error": None},
    },
    "replan": {
        "draft": {"status": "succeeded", "output": {"body": "x"}, "error": None},
    },
    "repair": {
        "draft": {"status": "succeeded", "output": {"body": "x"}, "error": None},
        "repair": {"status": "succeeded", "output": {"title": "fixed"}, "error": None},
    },
    "approval_wait": {
        "publish": {"status": "succeeded", "output": {"candidate": "x"}, "error": None},
    },
    "side_effect_publication": {
        "publish": {
            "status": "succeeded",
            "output": {"candidate": "report"},
            "error": None,
        },
    },
}


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


def test_graph_compiled_behavior_matches_v1_semantic_golden_fixture() -> None:
    expected = json.loads(_FIXTURE.read_text(encoding="utf-8"))
    actual = build_graph_compiled_golden_snapshot()

    assert actual["schema"] == expected["schema"]
    for fixture_name in _RUN_FIXTURE_NAMES:
        assert actual[fixture_name] == _legacy_semantic_projection(
            fixture_name,
            expected[fixture_name],
        ), fixture_name

    expected_workflow = expected["linear_research_workflow"]
    actual_workflow = actual["linear_research_workflow"]
    assert actual_workflow["step_ids"] == expected_workflow["step_ids"]
    assert actual_workflow["entry_step_id"] == expected_workflow["entry_step_id"]
    assert actual_workflow["terminal_policy"] == expected_workflow["terminal_policy"]
    assert actual_workflow["route_pairs"] == []
    assert expected_workflow["route_pairs"]

    research_workflow = build_paper_analysis_workflow_spec()
    assert actual_workflow["workflow_checksum"] == checksum_for(
        research_workflow.to_dict()
    )
    assert actual_workflow["workflow_checksum"] != expected_workflow[
        "workflow_checksum"
    ]
    assert actual_workflow["compiled_graph_checksum"].startswith("sha256:")
    recompiled_research = (
        HarnessWorkflowGraphCompiler()
        .compile(research_workflow)
        .graph
    )
    assert (
        actual_workflow["compiled_graph_checksum"]
        == recompiled_research.checksum
    )
    node_kinds = {
        node.node_id: node.node_kind.value for node in recompiled_research.nodes
    }
    assert {
        "analysis_fork": "fork_all",
        "analysis_join": "join_all",
        "analysis_join:merge": "merge",
    }.items() <= node_kinds.items()
    assert {
        (edge.source_id, edge.target_id, edge.branch_id)
        for edge in recompiled_research.edges
        if edge.edge_kind.value == "fork_branch"
    } == {
        ("analysis_fork", "analyze_structure", "structure"),
        ("analysis_fork", "analyze_contribution", "contribution"),
        ("analysis_fork", "analyze_experiments", "experiments"),
    }

    assert actual["checkpoint"] == expected["checkpoint"]
    assert {
        key: value
        for key, value in actual["final_business_result"].items()
        if key != "trace_event_types"
    } == {
        key: value
        for key, value in expected["final_business_result"].items()
        if key != "trace_event_types"
    }
    assert (
        "harness_transition_committed"
        in expected["final_business_result"]["trace_event_types"]
    )
    assert (
        "harness_transition_committed"
        not in actual["final_business_result"]["trace_event_types"]
    )

    graph_history = actual["durable_history"]
    assert (
        graph_history["decision_count"] == expected["durable_history"]["decision_count"]
    )
    assert graph_history["all_decisions_graph_native"] is True
    assert graph_history["decision_checksums_unique"] is True
    assert graph_history["legacy_transition_event_count"] == 0


def build_graph_compiled_golden_snapshot() -> dict[str, Any]:
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

    graph_decisions = tuple(
        decision
        for decision in linear.decisions
        if isinstance(decision, HarnessGraphDecision)
    )
    return {
        "schema": "newsroom.harness-graph-migration-golden/v1",
        "linear_research_workflow": {
            "workflow_checksum": checksum_for(research_workflow.to_dict()),
            "compiled_graph_checksum": compiled_research.checksum,
            "step_ids": list(research_workflow.step_ids),
            "entry_step_id": research_workflow.entry_step_id,
            "route_pairs": [
                [rule.from_step, rule.to_step]
                for rule in research_workflow.routing_rules
            ],
            "terminal_policy": research_workflow.terminal_side_effect_policy.to_dict(),
        },
        "linear_execution": _run_projection(linear),
        "conditional_route": _run_projection(conditional),
        "retry": _run_projection(retry),
        "replan": _run_projection(replan),
        "repair": _run_projection(repair),
        "approval_wait": _run_projection(approval),
        "side_effect_publication": {
            **_run_projection(side_effect),
            "side_effect_metrics": {
                "handler_calls": side_effect_handler.call_count,
                "decision_writes": side_effect_store.decision_write_count,
                "outcome_writes": side_effect_store.outcome_write_count,
            },
            "durable_reference_keys": sorted(
                key
                for step in side_effect.state.step_states
                for key in step.metadata
                if key.startswith("side_effect_")
            ),
        },
        "durable_history": {
            "schema": graph_decisions[0].schema_version,
            "decision_count": len(graph_decisions),
            "all_decisions_graph_native": len(graph_decisions) == len(linear.decisions),
            "decision_checksums_unique": len(
                {decision.decision_checksum for decision in graph_decisions}
            )
            == len(graph_decisions),
            "legacy_transition_event_count": sum(
                event.event_type.value == "harness_transition_committed"
                for event in linear.events
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
            HarnessStepSpec(
                "report", "llm", input_keys=("evidence",), output_key="report"
            ),
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
            "classify": lambda task: HarnessWorkerResult(
                "succeeded", output={"kind": "repair"}
            ),
            "normal": lambda task: HarnessWorkerResult(
                "succeeded", output={"normal": True}
            ),
            "repair": lambda task: HarnessWorkerResult(
                "succeeded", output={"fixed": True}
            ),
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
        worker_registry={
            "draft": lambda task: HarnessWorkerResult("succeeded", output={"body": "x"})
        },
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
            "draft": lambda task: HarnessWorkerResult(
                "succeeded", output={"body": "x"}
            ),
            "repair": lambda task: HarnessWorkerResult(
                "succeeded", output={"title": "fixed"}
            ),
        },
    ).run(HarnessRunSpec("golden-repair-run", workflow, created_at=_FIXED_AT))


def _approval_run():
    workflow = HarnessWorkflowSpec(
        workflow_id="golden-approval",
        steps=(
            HarnessStepSpec(
                "publish", "artifact", metadata={"approval_required": True}
            ),
        ),
        entry_step_id="publish",
    )
    return HarnessControlPlane(
        event_port=InMemoryHarnessEventPort(),
        worker_registry={
            "publish": lambda task: HarnessWorkerResult(
                "succeeded", output={"candidate": "x"}
            )
        },
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
        "trace_event_types": sorted(
            {event.event_type.value for event in result.trace.events}
        ),
    }


def _run_projection(result) -> dict[str, Any]:
    graph_state = result.graph_state
    assert graph_state is not None
    graph_budget_usage = {
        counter.name: counter.used for counter in graph_state.budgets.counters
    }
    return {
        "status": result.state.status.value,
        "current_step_id": result.state.current_step_id,
        "decisions": _graph_decisions_as_v1_semantics(result),
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
        "graph_budget_usage": {
            "turns": graph_budget_usage["turns"],
            "replans": graph_budget_usage["replans"],
            "worker_calls": graph_budget_usage["worker_calls"],
        },
        "terminal_reason": result.state.metadata.get("terminal_reason"),
        "worker_steps": sorted(result.worker_results),
        "outputs": {
            step_id: {
                "status": worker_result.status.value,
                "output": worker_result.candidate_payload()["output"],
                "error": worker_result.error,
            }
            for step_id, worker_result in sorted(result.worker_results.items())
        },
        "gates": [
            {
                "step_id": event.step_id,
                "gate": event.payload["gate"],
                "passed": event.payload["passed"],
            }
            for event in result.events
            if event.event_type.value == "gate_evaluated"
        ],
        "side_effects": {
            step_id: {
                "status": outcome.status.value,
                "disposition": outcome.disposition.value,
                "handler_ref": str(outcome.handler),
            }
            for step_id, outcome in sorted(result.side_effect_outcomes.items())
        },
        "graph_terminal": {
            "lifecycle": graph_state.lifecycle.value,
            "outcome": graph_state.outcome.value,
            "reason_code": graph_state.terminal_reason_code,
        },
        "event_protocol": {
            "all_decisions_graph_native": all(
                isinstance(decision, HarnessGraphDecision)
                for decision in result.decisions
            ),
            "legacy_transition_event_count": sum(
                event.event_type.value == "harness_transition_committed"
                for event in result.events
            ),
        },
    }


def _graph_decisions_as_v1_semantics(result) -> list[str]:
    graph_state = result.graph_state
    assert graph_state is not None
    executable_node_ids = {
        node.identity.node_id
        for node in graph_state.node_instances
        if node.step_id is not None
    }
    projected: list[str] = []
    routed_targets: set[str] = set()
    current_step_id: str | None = None
    started = False

    for decision in result.decisions:
        assert isinstance(decision, HarnessGraphDecision)
        if decision.decision_type is HarnessGraphDecisionType.ACTIVATE_NODE:
            node_id = decision.node_id
            assert node_id is not None
            if node_id not in executable_node_ids:
                continue
            if not started:
                projected.append(f"start_step:{node_id}:{node_id}")
                started = True
            elif node_id in routed_targets:
                routed_targets.remove(node_id)
            else:
                assert current_step_id is not None
                projected.append(f"route_to_step:{current_step_id}:{node_id}")
            continue

        if decision.decision_type is HarnessGraphDecisionType.SELECT_CHOICE:
            assert current_step_id is not None
            target_node_id = _single_target(decision)
            projected.append(f"route_to_step:{current_step_id}:{target_node_id}")
            routed_targets.add(target_node_id)
            continue

        transition_type = decision.payload.get("step_transition_type")
        if isinstance(transition_type, str):
            # The graph side-effect protocol splits the legacy completion
            # boundary into PREPARE_SIDE_EFFECT and COMPLETE_NODE.  The
            # latter is an internal durable acknowledgement, so omit it
            # from the v1 semantic projection to preserve one completion
            # event before COMPLETE_RUN.
            if (
                decision.decision_type is HarnessGraphDecisionType.COMPLETE_NODE
                and decision.payload.get("side_effect_prepare_decision_ref")
            ):
                continue
            step_id = decision.node_id or current_step_id
            assert step_id is not None
            legacy_transition_type = (
                "halt_run" if transition_type == "halt_step" else transition_type
            )
            target_step_id = decision.payload.get("target_step_id")
            if target_step_id is None and decision.target_node_ids:
                target_step_id = _single_target(decision)
            projected.append(
                f"{legacy_transition_type}:{step_id}:{target_step_id or '-'}"
            )
            current_step_id = step_id
            if decision.decision_type is HarnessGraphDecisionType.ROUTE_TO_REPAIR:
                assert isinstance(target_step_id, str)
                routed_targets.add(target_step_id)
            continue

        if decision.decision_type is HarnessGraphDecisionType.COMPLETE_RUN:
            assert current_step_id is not None
            projected.append(f"complete_run:{current_step_id}:-")
            continue
        if decision.decision_type is HarnessGraphDecisionType.PROJECT_RUN_WAITING:
            continue
        raise AssertionError(
            f"unmapped Graph migration decision: {decision.decision_type.value}"
        )
    return projected


def _single_target(decision: HarnessGraphDecision) -> str:
    assert len(decision.target_node_ids) == 1
    return decision.target_node_ids[0]


def _legacy_semantic_projection(
    fixture_name: str,
    legacy: dict[str, Any],
) -> dict[str, Any]:
    expected_outputs = _EXPECTED_OUTPUTS[fixture_name]
    expected_gates = _expected_gate_projection(fixture_name)
    assert sorted(expected_outputs) == legacy["worker_steps"]
    assert len(expected_gates) == legacy["event_type_counts"]["gate_evaluated"]
    projection = {
        "status": legacy["status"],
        "current_step_id": legacy["current_step_id"],
        "decisions": legacy["decisions"],
        "phase_sequence": [
            item
            for item in legacy["phase_sequence"]
            if item.split(":", maxsplit=2)[1] in {"plan", "execute", "verify"}
        ],
        "step_states": legacy["step_states"],
        "counters": legacy["counters"],
        "graph_budget_usage": legacy["counters"],
        "terminal_reason": legacy["terminal_reason"],
        "worker_steps": legacy["worker_steps"],
        "outputs": expected_outputs,
        "gates": expected_gates,
        "side_effects": legacy.get("outcomes", {}),
        "graph_terminal": _legacy_graph_terminal(
            legacy["status"],
            legacy["terminal_reason"],
        ),
        "event_protocol": {
            "all_decisions_graph_native": True,
            "legacy_transition_event_count": 0,
        },
    }
    if fixture_name == "side_effect_publication":
        projection["side_effect_metrics"] = {
            "handler_calls": legacy["handler_calls"],
            "decision_writes": legacy["decision_writes"],
            "outcome_writes": legacy["outcome_writes"],
        }
        projection["durable_reference_keys"] = legacy["durable_reference_keys"]
    return projection


def _legacy_graph_terminal(status: str, terminal_reason: str | None) -> dict[str, Any]:
    lifecycle_and_outcome = {
        "succeeded": ("completed", "succeeded"),
        "failed": ("completed", "failed"),
        "cancelled": ("completed", "cancelled"),
        "waiting_approval": ("waiting", "none"),
        "halted": ("halted", "none"),
    }
    lifecycle, outcome = lifecycle_and_outcome[status]
    reason_codes = {
        "verification failed and replan budget is exhausted": (
            "verification_failed_replans_exhausted"
        ),
    }
    return {
        "lifecycle": lifecycle,
        "outcome": outcome,
        "reason_code": reason_codes.get(terminal_reason),
    }


def _expected_gate_projection(fixture_name: str) -> list[dict[str, Any]]:
    if fixture_name == "linear_execution":
        return [*_step_gates("collect"), *_step_gates("report")]
    if fixture_name == "conditional_route":
        return [
            *_step_gates("classify", extra_verify_gates=("golden_routing",)),
            *_step_gates("repair"),
        ]
    if fixture_name == "retry":
        return _step_gates("call")
    if fixture_name == "replan":
        failed_attempt = _step_gates("draft", output_schema_passed=False)
        return [*failed_attempt, *failed_attempt]
    if fixture_name == "repair":
        return [
            *_step_gates("draft", output_schema_passed=False),
            *_step_gates("repair"),
        ]
    if fixture_name == "approval_wait":
        return _plan_gates("publish")
    if fixture_name == "side_effect_publication":
        return _step_gates("publish")
    raise AssertionError(f"unknown migration fixture: {fixture_name}")


def _step_gates(
    step_id: str,
    *,
    output_schema_passed: bool = True,
    extra_verify_gates: tuple[str, ...] = (),
) -> list[dict[str, Any]]:
    verify_gates = (
        ("tool_allowlist", True),
        ("output_schema", output_schema_passed),
        ("deduplication", True),
        ("score_range", True),
        ("budget", True),
        ("skill_evolution_budget", True),
        *((gate, True) for gate in extra_verify_gates),
    )
    return [
        *_plan_gates(step_id),
        *(
            {"step_id": step_id, "gate": gate, "passed": passed}
            for gate, passed in verify_gates
        ),
    ]


def _plan_gates(step_id: str) -> list[dict[str, Any]]:
    return [
        {"step_id": step_id, "gate": gate, "passed": True}
        for gate in (
            "tool_allowlist",
            "deduplication",
            "budget",
            "skill_evolution_budget",
        )
    ]


__all__ = ["build_graph_compiled_golden_snapshot"]
