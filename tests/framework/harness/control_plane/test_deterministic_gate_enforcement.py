from __future__ import annotations

from typing import Literal, cast

import pytest

from framework.harness import (
    HarnessBudget,
    HarnessControlPlane,
    HarnessEventType,
    HarnessGraphDecisionType,
    HarnessGraphObservationType,
    HarnessRunSpec,
    HarnessRunStatus,
    HarnessStepSpec,
    HarnessValidationError,
    HarnessWorkerResult,
    InMemoryHarnessEventPort,
)
from framework.harness.workflow.spec import (
    HarnessRouteKind,
    HarnessRoutingRule,
    HarnessWorkflowSpec,
)
from framework.harness.control_plane.gate_registry import (
    DeterministicGateRegistry,
    GateReference,
    GateRegistration,
)
from framework.harness.control_plane.gates import (
    DeterministicGate,
    GateContext,
    HarnessGateResult,
)
class _RecordingGate(DeterministicGate):
    def __init__(
        self,
        gate_name: str,
        calls: list[tuple[str, str]],
        *,
        passed: bool = True,
        score: float | None = None,
    ) -> None:
        self.gate_name = gate_name
        self._calls = calls
        self._passed = passed
        self._score = score

    def evaluate(self, context: GateContext) -> HarnessGateResult:
        self._calls.append((context.step_spec.step_id, self.gate_name))
        details = {} if self._score is None else {"score": self._score}
        return HarnessGateResult(
            gate_name=self.gate_name,
            passed=self._passed,
            reason=None if self._passed else f"{self.gate_name} rejected candidate",
            details=details,
        )


class _MalformedGate(DeterministicGate):
    gate_name = "CandidateGate"

    def __init__(self, failure: Literal["exception", "identity_mismatch", "missing"]) -> None:
        self._failure = failure

    def evaluate(self, context: GateContext) -> HarnessGateResult:
        if self._failure == "exception":
            raise RuntimeError("gate implementation failed")
        if self._failure == "identity_mismatch":
            return HarnessGateResult(gate_name="DifferentGate", passed=True)
        return cast(HarnessGateResult, None)


class _DetailsGate(DeterministicGate):
    gate_name = "CandidateGate"

    def __init__(self, details: dict[str, object]) -> None:
        self._details = details

    def evaluate(self, context: GateContext) -> HarnessGateResult:
        del context
        return HarnessGateResult(
            gate_name=self.gate_name,
            passed=True,
            details=self._details,
        )


def test_unknown_declared_gate_fails_before_any_event_or_worker_call() -> None:
    event_port = InMemoryHarnessEventPort()
    worker_calls: list[dict[str, object]] = []
    workflow = _workflow(
        HarnessStepSpec(
            step_id="draft",
            worker_type="llm",
            quality_gate="DefinitelyMissingGate@1",
        )
    )
    control_plane = HarnessControlPlane(
        event_port=event_port,
        worker_registry={
            "draft": lambda task: _record_worker_call(worker_calls, task),
        },
        gate_registry=DeterministicGateRegistry(),
    )

    with pytest.raises(HarnessValidationError) as captured:
        control_plane.run(HarnessRunSpec(run_id="run-unknown-gate", workflow=workflow))

    assert captured.value.code == "unknown_gate_reference"
    assert worker_calls == []
    assert event_port.events == []
    _assert_no_graph_run(event_port, "run-unknown-gate")


def test_mandatory_gate_moving_version_alias_fails_before_run_creation() -> None:
    event_port = InMemoryHarnessEventPort()
    worker_calls: list[dict[str, object]] = []
    gate = _PassingGate()
    gate.gate_version = "latest"

    with pytest.raises(HarnessValidationError) as captured:
        HarnessControlPlane(
            event_port=event_port,
            worker_registry={
                "draft": lambda task: _record_worker_call(worker_calls, task),
            },
            verify_gates=(gate,),
        ).run(
            HarnessRunSpec(
                run_id="run-moving-mandatory-gate",
                workflow=_workflow(
                    HarnessStepSpec(step_id="draft", worker_type="llm")
                ),
            )
        )

    assert captured.value.code == "invalid_gate_reference"
    assert worker_calls == []
    assert event_port.events == []
    _assert_no_graph_run(event_port, "run-moving-mandatory-gate")


def test_worker_quality_observation_does_not_create_a_verdict() -> None:
    mandatory_calls: list[tuple[str, str]] = []
    result = HarnessControlPlane(
        event_port=InMemoryHarnessEventPort(),
        worker_registry={
            "utility": lambda task: HarnessWorkerResult(
                status="succeeded",
                output={"quality_observation": {"score": 0.99}},
            ),
        },
        verify_gates=(_RecordingGate("mandatory", mandatory_calls),),
        gate_registry=DeterministicGateRegistry(),
    ).run(
        HarnessRunSpec(
            run_id="run-observation-only",
            workflow=_workflow(HarnessStepSpec(step_id="utility", worker_type="llm")),
        )
    )

    assert result.state.status == HarnessRunStatus.SUCCEEDED
    assert result.quality_verdicts == {}
    assert mandatory_calls == [("utility", "mandatory")]


def test_high_worker_quality_observation_cannot_override_failed_gate_or_route() -> None:
    domain_calls: list[tuple[str, str]] = []
    target_calls: list[dict[str, object]] = []
    gate = _RecordingGate("CandidateGate", domain_calls, passed=False, score=0.1)
    workflow = HarnessWorkflowSpec(
        workflow_id="gate-owned-route",
        steps=(
            HarnessStepSpec(
                step_id="draft",
                worker_type="llm",
                quality_gate="CandidateGate@1",
            ),
            HarnessStepSpec(step_id="publish", worker_type="artifact"),
        ),
        entry_step_id="draft",
        routing_rules=(
            HarnessRoutingRule(
                from_step="draft",
                to_step="publish",
                kind=HarnessRouteKind.ON_VERDICT,
                condition={"passed": True, "min_score": 0.9},
            ),
        ),
    )
    result = HarnessControlPlane(
        event_port=InMemoryHarnessEventPort(),
        worker_registry={
            "draft": lambda task: HarnessWorkerResult(
                status="succeeded",
                output={"quality_observation": {"score": 0.99}},
            ),
            "publish": lambda task: _record_worker_call(target_calls, task),
        },
        verify_gates=(_PassingGate(),),
        gate_registry=_registry(_registration("CandidateGate@1", gate)),
    ).run(
        HarnessRunSpec(
            run_id="run-gate-owned-route",
            workflow=workflow,
            budget=HarnessBudget(
                max_turns=20,
                max_replans=0,
                max_retries_per_step=0,
                max_worker_calls=10,
            ),
        )
    )

    assert result.state.status == HarnessRunStatus.HALTED
    assert result.quality_verdicts["draft"].passed is False
    assert result.quality_verdicts["draft"].score == 0.1
    assert domain_calls == [("draft", "CandidateGate")]
    assert target_calls == []
    assert not any(
        decision.decision_type is HarnessGraphDecisionType.SELECT_CHOICE
        and "publish" in decision.target_node_ids
        for decision in result.decisions
    )


def test_on_verdict_route_uses_gate_verdict_instead_of_worker_observation() -> None:
    domain_calls: list[tuple[str, str]] = []
    normal_calls: list[dict[str, object]] = []
    selected_calls: list[dict[str, object]] = []
    gate = _RecordingGate("CandidateGate", domain_calls, score=0.95)
    workflow = HarnessWorkflowSpec(
        workflow_id="positive-gate-route",
        steps=(
            HarnessStepSpec(
                step_id="classify",
                worker_type="llm",
                quality_gate="CandidateGate@1",
            ),
            HarnessStepSpec(step_id="normal", worker_type="llm"),
            HarnessStepSpec(step_id="selected", worker_type="llm"),
        ),
        entry_step_id="classify",
        routing_rules=(
            HarnessRoutingRule(
                from_step="classify",
                to_step="selected",
                kind=HarnessRouteKind.ON_VERDICT,
                condition={"passed": True, "min_score": 0.9},
            ),
        ),
    )
    result = HarnessControlPlane(
        event_port=InMemoryHarnessEventPort(),
        worker_registry={
            "classify": lambda task: HarnessWorkerResult(
                status="succeeded",
                output={"quality_observation": {"score": 0.01}},
            ),
            "normal": lambda task: _record_worker_call(normal_calls, task),
            "selected": lambda task: _record_worker_call(selected_calls, task),
        },
        verify_gates=(_PassingGate(),),
        gate_registry=_registry(_registration("CandidateGate@1", gate)),
    ).run(HarnessRunSpec(run_id="run-positive-gate-route", workflow=workflow))

    assert result.state.status == HarnessRunStatus.SUCCEEDED
    assert result.quality_verdicts["classify"].passed is True
    assert result.quality_verdicts["classify"].score == 0.95
    assert domain_calls == [("classify", "CandidateGate")]
    assert normal_calls == []
    assert len(selected_calls) == 1
    routed = [
        decision
        for decision in result.decisions
        if decision.decision_type is HarnessGraphDecisionType.SELECT_CHOICE
    ]
    assert routed[0].target_node_ids == ("selected",)


def test_worker_quality_score_is_rejected_as_a_control_field() -> None:
    with pytest.raises(HarnessValidationError) as captured:
        HarnessWorkerResult(status="succeeded", output={"quality_score": 0.99})

    assert captured.value.details["forbidden"] == ["quality_score"]


def test_each_verify_runs_mandatory_and_only_its_bound_gate_dependencies() -> None:
    calls: list[tuple[str, str]] = []
    registry = _registry(
        _registration(
            "FirstGate@1",
            _RecordingGate("FirstGate", calls),
            dependencies=("SchemaGate@1", "EvidenceGate@1"),
        ),
        _registration(
            "SecondGate@1",
            _RecordingGate("SecondGate", calls),
            dependencies=("LineageGate@1",),
        ),
        _registration(
            "SchemaGate@1",
            _RecordingGate("SchemaGate", calls),
            dependencies=("LineageGate@1",),
        ),
        _registration(
            "EvidenceGate@1",
            _RecordingGate("EvidenceGate", calls),
            dependencies=("LineageGate@1",),
        ),
        _registration("LineageGate@1", _RecordingGate("LineageGate", calls)),
        _registration("UnrelatedGate@1", _RecordingGate("UnrelatedGate", calls)),
    )
    workflow = HarnessWorkflowSpec(
        workflow_id="per-step-gates",
        steps=(
            HarnessStepSpec(
                step_id="first",
                worker_type="llm",
                quality_gate="FirstGate@1",
            ),
            HarnessStepSpec(
                step_id="second",
                worker_type="llm",
                quality_gate="SecondGate@1",
            ),
        ),
        entry_step_id="first",
    )

    result = HarnessControlPlane(
        event_port=InMemoryHarnessEventPort(),
        worker_registry={
            "first": _successful_worker,
            "second": _successful_worker,
        },
        verify_gates=(_RecordingGate("mandatory", calls),),
        gate_registry=registry,
    ).run(HarnessRunSpec(run_id="run-per-step-gates", workflow=workflow))

    assert result.state.status == HarnessRunStatus.SUCCEEDED
    assert calls == [
        ("first", "mandatory"),
        ("first", "LineageGate"),
        ("first", "SchemaGate"),
        ("first", "EvidenceGate"),
        ("first", "FirstGate"),
        ("second", "mandatory"),
        ("second", "LineageGate"),
        ("second", "SecondGate"),
    ]


def test_declared_gate_cannot_be_shadowed_by_a_different_mandatory_implementation() -> None:
    calls: list[tuple[str, str]] = []
    worker_calls: list[dict[str, object]] = []
    mandatory = _RecordingGate("CandidateGate", calls, passed=True)
    declared = _RecordingGate("CandidateGate", calls, passed=False)
    event_port = InMemoryHarnessEventPort()

    with pytest.raises(HarnessValidationError) as captured:
        HarnessControlPlane(
            event_port=event_port,
            worker_registry={
                "draft": lambda task: _record_worker_call(worker_calls, task)
            },
            verify_gates=(mandatory,),
            gate_registry=_registry(
                _registration("CandidateGate@1", declared),
            ),
        ).run(
            HarnessRunSpec(
                run_id="run-conflicting-gate-implementation",
                workflow=_workflow(
                    HarnessStepSpec(
                        step_id="draft",
                        worker_type="llm",
                        quality_gate="CandidateGate@1",
                    )
                ),
            )
        )

    assert captured.value.code == "conflicting_gate_implementation"
    assert captured.value.details["reference"] == "CandidateGate@1"
    assert worker_calls == []
    assert calls == []
    assert event_port.events == []


def test_same_bound_gate_instance_is_deduplicated_across_mandatory_and_declared_roles() -> None:
    calls: list[tuple[str, str]] = []
    gate = _RecordingGate("CandidateGate", calls)

    result = HarnessControlPlane(
        event_port=InMemoryHarnessEventPort(),
        worker_registry={"draft": _successful_worker},
        verify_gates=(gate,),
        gate_registry=_registry(_registration("CandidateGate@1", gate)),
    ).run(
        HarnessRunSpec(
            run_id="run-deduplicated-gate-instance",
            workflow=_workflow(
                HarnessStepSpec(
                    step_id="draft",
                    worker_type="llm",
                    quality_gate="CandidateGate@1",
                )
            ),
        )
    )

    assert result.succeeded is True
    assert calls == [("draft", "CandidateGate")]


@pytest.mark.parametrize(
    ("failure", "reason_code"),
    (
        ("exception", "gate_exception"),
        ("identity_mismatch", "gate_identity_mismatch"),
        ("missing", "invalid_gate_result"),
    ),
)
def test_invalid_declared_gate_result_fails_closed(
    failure: Literal["exception", "identity_mismatch", "missing"],
    reason_code: str,
) -> None:
    event_port = InMemoryHarnessEventPort()
    result = HarnessControlPlane(
        event_port=event_port,
        worker_registry={"draft": _successful_worker},
        verify_gates=(_PassingGate(),),
        gate_registry=_registry(
            _registration("CandidateGate@1", _MalformedGate(failure)),
        ),
    ).run(
        HarnessRunSpec(
            run_id=f"run-invalid-gate-{failure}",
            workflow=_workflow(
                HarnessStepSpec(
                    step_id="draft",
                    worker_type="llm",
                    quality_gate="CandidateGate@1",
                )
            ),
            budget=HarnessBudget(
                max_turns=20,
                max_replans=0,
                max_retries_per_step=0,
                max_worker_calls=10,
            ),
        )
    )

    assert result.state.status == HarnessRunStatus.HALTED
    assert result.quality_verdicts["draft"].passed is False
    gate_event = next(
        event
        for event in event_port.events
        if event.event_type == HarnessEventType.GATE_EVALUATED
        and event.payload.get("details", {})
        .get("harness_gate", {})
        .get("reference")
        == "CandidateGate@1"
    )
    assert gate_event.payload["gate"] == "CandidateGate"
    assert gate_event.payload["passed"] is False
    assert gate_event.payload["details"]["harness_gate"]["reason_code"] == reason_code


@pytest.mark.parametrize(
    "details",
    (
        pytest.param({"score": "0.1"}, id="string-score"),
        pytest.param({"score": True}, id="boolean-score"),
        pytest.param({"score": 2.0}, id="out-of-range-score"),
        pytest.param({"score": float("nan")}, id="nan-score"),
        pytest.param({"score": float("inf")}, id="infinite-score"),
        pytest.param({"repair_hints": "rewrite"}, id="string-repair-hints"),
        pytest.param({"repair_hints": ["rewrite", 1]}, id="non-string-repair-hint"),
        pytest.param({"opaque": object()}, id="non-canonical-details"),
    ),
)
def test_malformed_gate_details_become_a_stable_failed_result(
    details: dict[str, object],
) -> None:
    event_port = InMemoryHarnessEventPort()
    result = HarnessControlPlane(
        event_port=event_port,
        worker_registry={"draft": _successful_worker},
        verify_gates=(_PassingGate(),),
        gate_registry=_registry(
            _registration("CandidateGate@1", _DetailsGate(details)),
        ),
    ).run(
        HarnessRunSpec(
            run_id="run-malformed-gate-details",
            workflow=_workflow(
                HarnessStepSpec(
                    step_id="draft",
                    worker_type="llm",
                    quality_gate="CandidateGate@1",
                )
            ),
            budget=HarnessBudget(
                max_turns=20,
                max_replans=0,
                max_retries_per_step=0,
                max_worker_calls=10,
            ),
        )
    )

    assert result.state.status == HarnessRunStatus.HALTED
    assert result.quality_verdicts["draft"].passed is False
    gate_event = next(
        event
        for event in event_port.events
        if event.event_type == HarnessEventType.GATE_EVALUATED
        and event.payload.get("gate") == "CandidateGate"
    )
    assert gate_event.payload["passed"] is False
    assert (
        gate_event.payload["details"]["harness_gate"]["reason_code"]
        == "invalid_gate_result"
    )


def test_on_verdict_route_without_declared_gate_fails_preflight() -> None:
    event_port = InMemoryHarnessEventPort()
    worker_calls: list[dict[str, object]] = []
    workflow = HarnessWorkflowSpec(
        workflow_id="invalid-verdict-route",
        steps=(
            HarnessStepSpec(step_id="draft", worker_type="llm"),
            HarnessStepSpec(step_id="publish", worker_type="artifact"),
        ),
        entry_step_id="draft",
        routing_rules=(
            HarnessRoutingRule(
                from_step="draft",
                to_step="publish",
                kind=HarnessRouteKind.ON_VERDICT,
                condition={"passed": True},
            ),
        ),
    )
    control_plane = HarnessControlPlane(
        event_port=event_port,
        worker_registry={
            "draft": lambda task: _record_worker_call(worker_calls, task),
        },
        gate_registry=DeterministicGateRegistry(),
    )

    with pytest.raises(HarnessValidationError) as captured:
        control_plane.run(HarnessRunSpec(run_id="run-invalid-verdict-route", workflow=workflow))

    assert "verdict" in str(captured.value).lower()
    assert worker_calls == []
    assert event_port.events == []
    _assert_no_graph_run(event_port, "run-invalid-verdict-route")


def test_verify_transition_and_decision_history_bind_gate_evidence_and_verdict() -> None:
    calls: list[tuple[str, str]] = []
    event_port = InMemoryHarnessEventPort()
    result = HarnessControlPlane(
        event_port=event_port,
        worker_registry={"draft": _successful_worker},
        verify_gates=(_PassingGate(),),
        gate_registry=_registry(
            _registration(
                "CandidateGate@1",
                _RecordingGate("CandidateGate", calls, score=0.8),
            )
        ),
    ).run(
        HarnessRunSpec(
            run_id="run-versioned-gate-evidence",
            workflow=_workflow(
                HarnessStepSpec(
                    step_id="draft",
                    worker_type="llm",
                    quality_gate="CandidateGate@1",
                )
            ),
        )
    )

    verify_phase = next(
        event
        for event in result.events
        if event.event_type == HarnessEventType.PHASE_RECORDED
        and event.payload["phase"] == "verify"
        and event.payload["boundary"] == "exit"
    )
    verdict = result.quality_verdicts["draft"]
    recovery = event_port.recover_graph(result.state.run_spec.run_id)
    gate_observations = tuple(
        commit.observation
        for commit in recovery.observation_commits
        if commit.observation.observation_type
        is HarnessGraphObservationType.GATE_RESULT
    )
    quality_observation = next(
        commit.observation
        for commit in recovery.observation_commits
        if commit.observation.observation_type
        is HarnessGraphObservationType.QUALITY_VERDICT
    )
    complete_commit = next(
        commit
        for commit in recovery.decision_commits
        if commit.decision.decision_type is HarnessGraphDecisionType.COMPLETE_NODE
    )
    completion_projection = next(
        commit
        for commit in recovery.projection_commits
        if commit.cause_checksum == complete_commit.decision.decision_checksum
    )

    assert len(gate_observations) == len(verify_phase.payload["gate_results"])
    assert all(item.payload["passed"] for item in gate_observations)
    assert quality_observation.payload == {"passed": True, "score": 0.8}
    assert quality_observation.evidence_ref in complete_commit.accepted_evidence_refs
    assert {
        item.evidence_ref for item in gate_observations
    } <= set(complete_commit.accepted_evidence_refs)
    assert completion_projection.sequence == complete_commit.sequence + 1
    assert verdict.passed is True
    assert verdict.score == 0.8


class _PassingGate(DeterministicGate):
    gate_name = "mandatory"

    def evaluate(self, context: GateContext) -> HarnessGateResult:
        return HarnessGateResult(gate_name=self.gate_name, passed=True)


def _workflow(step: HarnessStepSpec) -> HarnessWorkflowSpec:
    return HarnessWorkflowSpec(
        workflow_id=f"workflow-{step.step_id}",
        steps=(step,),
        entry_step_id=step.step_id,
    )


def _assert_no_graph_run(event_port: InMemoryHarnessEventPort, run_id: str) -> None:
    recovery = event_port.recover_graph(run_id)
    assert recovery.graph is None
    assert recovery.run_spec_checksum is None
    assert recovery.state is None
    assert recovery.expected_last_sequence == 0
    assert recovery.decision_commits == ()
    assert recovery.projection_commits == ()
    assert recovery.activity_result_commits == ()
    assert recovery.observation_commits == ()
    assert recovery.activities == ()


def _registration(
    reference: str,
    gate: DeterministicGate,
    *,
    dependencies: tuple[str, ...] = (),
) -> GateRegistration:
    return GateRegistration(
        reference=GateReference.parse(reference),
        gate=gate,
        dependencies=tuple(GateReference.parse(item) for item in dependencies),
    )


def _registry(*registrations: GateRegistration) -> DeterministicGateRegistry:
    return DeterministicGateRegistry(registrations)


def _successful_worker(task: dict[str, object]) -> HarnessWorkerResult:
    return HarnessWorkerResult(status="succeeded", output={"candidate": True})


def _record_worker_call(
    calls: list[dict[str, object]],
    task: dict[str, object],
) -> HarnessWorkerResult:
    calls.append(dict(task))
    return _successful_worker(task)
