from __future__ import annotations

from dataclasses import dataclass, replace

import pytest

from framework.events.canonical import checksum_for
from framework.harness import (
    CountingHarnessSideEffectHandler,
    DeterministicGate,
    HarnessBudget,
    HarnessControlPlane,
    HarnessGateResult,
    HarnessRunSpec,
    HarnessRunStatus,
    HarnessRetryPolicy,
    HarnessSideEffectHandlerBinding,
    HarnessSideEffectIntent,
    HarnessSideEffectRegistry,
    HarnessStepSpec,
    HarnessTerminalSideEffectPolicy,
    HarnessValidationError,
    HarnessWorkerResult,
    HarnessWorkflowSpec,
    InMemoryHarnessEventPort,
    InMemoryHarnessSideEffectApprovalResolver,
    InMemoryHarnessSideEffectStore,
    harness_worker_candidate_ref,
)
from framework.harness.control_plane.graph_decision import HarnessGraphDecisionType
from framework.harness.control_plane.graph_evaluator import HarnessGraphObservationType
from framework.harness.control_plane.graph_runtime import HarnessGraphCommitKind


IDENTITY_SCOPE_REF = checksum_for({"tenant_id": "tenant-1"})
SUBJECT_SCOPE_REF = checksum_for({"paper_id": "paper-1"})


class _FailGate(DeterministicGate):
    gate_name = "injected_failure"

    def evaluate(self, context) -> HarnessGateResult:
        del context
        return HarnessGateResult(gate_name=self.gate_name, passed=False, reason="injected")


class _FailOnceGate(DeterministicGate):
    gate_name = "injected_failure_once"

    def __init__(self) -> None:
        self.call_count = 0

    def evaluate(self, context) -> HarnessGateResult:
        del context
        self.call_count += 1
        return HarnessGateResult(
            gate_name=self.gate_name,
            passed=self.call_count > 1,
            reason="injected" if self.call_count == 1 else None,
        )


class _FailAfterAuthorizationStore(InMemoryHarnessSideEffectStore):
    def __init__(self) -> None:
        super().__init__()
        self.failed = False

    def put_decision(self, decision):
        committed = super().put_decision(decision)
        if not self.failed:
            self.failed = True
            raise RuntimeError("injected crash after side-effect authorization")
        return committed


class _FailBeforeAuthorizationStore(InMemoryHarnessSideEffectStore):
    def __init__(self) -> None:
        super().__init__()
        self.failed = False

    def put_decision(self, decision):
        if not self.failed:
            self.failed = True
            raise RuntimeError("injected crash before side-effect authorization")
        return super().put_decision(decision)


class _FailBeforeGraphProjectionPort(InMemoryHarnessEventPort):
    def __init__(self, decision_type: HarnessGraphDecisionType) -> None:
        super().__init__()
        self.decision_type = decision_type
        self.failed = False

    def commit_graph_projection(self, projection, **kwargs):
        if (
            not self.failed
            and projection.commit_kind is HarnessGraphCommitKind.DECISION_PROJECTION
        ):
            recovery = self._graph_transition_port.recover_graph(
                projection.state.run_id
            )
            causal = next(
                (
                    item.decision
                    for item in recovery.pending_decisions
                    if item.decision.decision_checksum == projection.cause_checksum
                ),
                None,
            )
            if causal is not None and causal.decision_type is self.decision_type:
                self.failed = True
                raise RuntimeError(
                    f"injected crash before {self.decision_type.value} projection"
                )
        return super().commit_graph_projection(projection, **kwargs)


class _EffectThenRecoverHandler:
    def __init__(self, store: InMemoryHarnessSideEffectStore) -> None:
        self._delegate = CountingHarnessSideEffectHandler(store)
        self.external_effect_ids: set[str] = set()
        self.call_count = 0

    def prepare(self, intent, authorization):
        self.call_count += 1
        if intent.effect_id not in self.external_effect_ids:
            self.external_effect_ids.add(intent.effect_id)
            raise RuntimeError("injected crash after external effect")
        return self._delegate.prepare(intent, authorization)

    def commit(self, intent, authorization):
        return self.prepare(intent, authorization)


@dataclass
class _EffectSurfaceCounts:
    tool_calls: int = 0
    memory_writes: int = 0
    published_artifact_writes: int = 0
    release_writes: int = 0
    active_skill_writes: int = 0

    def snapshot(self) -> tuple[int, int, int, int, int]:
        return (
            self.tool_calls,
            self.memory_writes,
            self.published_artifact_writes,
            self.release_writes,
            self.active_skill_writes,
        )


class _EffectSurfaceProbe:
    """Tracks every forbidden commit surface behind one authorized handler call."""

    def __init__(self, store: InMemoryHarnessSideEffectStore) -> None:
        self._delegate = CountingHarnessSideEffectHandler(store)
        self.counts = _EffectSurfaceCounts()

    @property
    def call_count(self) -> int:
        return self._delegate.call_count

    def prepare(self, intent, authorization):
        self.counts.tool_calls += 1
        self.counts.memory_writes += 1
        self.counts.published_artifact_writes += 1
        self.counts.release_writes += 1
        self.counts.active_skill_writes += 1
        return self._delegate.prepare(intent, authorization)

    def commit(self, intent, authorization):
        return self.prepare(intent, authorization)


def _candidate_result(task: dict, *, output: dict | None = None) -> HarnessWorkerResult:
    candidate_output = output or {"candidate": "ok"}
    candidate_payload = {
        "status": "succeeded",
        "output": candidate_output,
        "artifacts": ["candidate://run-1/report"],
        "diagnostics": {},
        "metrics": {},
        "error": None,
    }
    attempt = task["harness_activity"]["attempt"]
    intent = HarnessSideEffectIntent(
        effect_id=f"effect-{attempt}",
        kind="artifact",
        run_id=task["run_id"],
        origin="worker",
        atomic_group="research-run-1",
        identity_scope_ref=IDENTITY_SCOPE_REF,
        subject_scope_ref=SUBJECT_SCOPE_REF,
        attempt=attempt,
        step_id=task["step_id"],
        worker_result_ref=harness_worker_candidate_ref(candidate_payload),
        candidate_checksum=checksum_for({"candidate": candidate_output}),
        handler="research.prepare@1",
        payload={"members": ["report"]},
        candidate_refs=("candidate://run-1/report",),
    )
    return HarnessWorkerResult(
        status="succeeded",
        output=candidate_output,
        artifacts=("candidate://run-1/report",),
        effect_intent=intent,
    )


def _workflow(
    *,
    terminal: bool = False,
    effect_attempt_limit: int = 1,
    approval_required: bool = False,
) -> HarnessWorkflowSpec:
    terminal_policy = None
    if terminal:
        terminal_policy = HarnessTerminalSideEffectPolicy(
            policy_id="research-terminal",
            version="1",
            handler="research.terminal@1",
            kind="artifact",
            requires_approval=False,
            retry_limit=effect_attempt_limit,
            not_required_evidence_ref=checksum_for({"approval": "not_required"}),
        )
    return HarnessWorkflowSpec(
        workflow_id="side-effect-workflow",
        steps=(
            HarnessStepSpec(
                step_id="publish",
                worker_type="artifact",
                output_key="candidate",
                retry_policy=HarnessRetryPolicy(max_attempts=effect_attempt_limit),
                metadata={"approval_required": approval_required},
                side_effect_handler="research.prepare@1",
            ),
        ),
        entry_step_id="publish",
        terminal_side_effect_policy=terminal_policy,
    )


def _run_spec(
    *,
    terminal: bool = False,
    effect_attempt_limit: int = 1,
    approval_required: bool = False,
    max_replans: int = 0,
    max_turns: int = 10,
) -> HarnessRunSpec:
    return HarnessRunSpec(
        run_id="run-1",
        workflow=_workflow(
            terminal=terminal,
            effect_attempt_limit=effect_attempt_limit,
            approval_required=approval_required,
        ),
        metadata={
            "identity_scope_ref": IDENTITY_SCOPE_REF,
            "subject_scope_ref": SUBJECT_SCOPE_REF,
        },
        budget=HarnessBudget(
            max_turns=max_turns,
            max_replans=max_replans,
            max_retries_per_step=effect_attempt_limit - 1,
            max_worker_calls=2,
        ),
    )


def _assert_graph_side_effect_commit_order(
    event_port,
    *,
    run_id: str,
    authorization,
    outcome,
) -> None:
    recovery = event_port.recover_graph(run_id)
    prepare_commits = tuple(
        commit
        for commit in recovery.decision_commits
        if commit.decision.decision_type
        is HarnessGraphDecisionType.PREPARE_SIDE_EFFECT
        and commit.decision.decision_checksum == authorization.causation_id
    )
    assert len(prepare_commits) == 1
    prepare_commit = prepare_commits[0]
    outcome_commits = tuple(
        commit
        for commit in recovery.observation_commits
        if commit.observation.observation_type
        is HarnessGraphObservationType.SIDE_EFFECT_OUTCOME
        and commit.observation.payload["prepare_decision_ref"]
        == prepare_commit.decision.decision_checksum
    )
    assert len(outcome_commits) == 1
    outcome_commit = outcome_commits[0]
    complete_commits = tuple(
        commit
        for commit in recovery.decision_commits
        if commit.decision.decision_type is HarnessGraphDecisionType.COMPLETE_NODE
        and commit.decision.payload.get("side_effect_prepare_decision_ref")
        == prepare_commit.decision.decision_checksum
    )
    assert len(complete_commits) == 1
    complete_commit = complete_commits[0]

    assert authorization.command_ordinal == prepare_commit.sequence
    assert authorization.causation_id == prepare_commit.decision.decision_checksum
    assert prepare_commit.sequence < outcome_commit.sequence < complete_commit.sequence
    assert outcome.decision_ref == authorization.checksum
    assert outcome_commit.observation.payload["decision_ref"] == authorization.checksum
    assert outcome_commit.observation.payload["outcome_ref"] == outcome.checksum
    assert outcome_commit.observation.evidence_ref == outcome.checksum
    assert complete_commit.decision.payload["side_effect_outcome_ref"] == outcome.checksum
    assert complete_commit.side_effect_outcome_ref == outcome.checksum
    assert outcome.checksum in complete_commit.accepted_evidence_refs


def test_preflight_rejects_unknown_handler_before_run_or_worker_call() -> None:
    event_port = InMemoryHarnessEventPort()
    worker_calls = 0

    def worker(task: dict) -> HarnessWorkerResult:
        nonlocal worker_calls
        worker_calls += 1
        return _candidate_result(task)

    control_plane = HarnessControlPlane(
        event_port=event_port,
        worker_registry={"publish": worker},
        side_effect_store=InMemoryHarnessSideEffectStore(),
    )

    with pytest.raises(HarnessValidationError) as captured:
        control_plane.run(_run_spec())

    assert captured.value.code == "unknown_side_effect_handler"
    assert worker_calls == 0
    assert event_port.events == []


def test_preflight_rejects_terminal_kind_mismatch_before_run_or_worker_call() -> None:
    event_port = InMemoryHarnessEventPort()
    store = InMemoryHarnessSideEffectStore()
    prepare_handler = CountingHarnessSideEffectHandler(store)
    terminal_handler = CountingHarnessSideEffectHandler(store, disposition="accepted")
    worker_calls = 0

    def worker(task: dict) -> HarnessWorkerResult:
        nonlocal worker_calls
        worker_calls += 1
        return _candidate_result(task)

    control_plane = HarnessControlPlane(
        event_port=event_port,
        worker_registry={"publish": worker},
        side_effect_registry=HarnessSideEffectRegistry(
            (
                HarnessSideEffectHandlerBinding(
                    "research.prepare@1", "artifact", prepare_handler
                ),
                HarnessSideEffectHandlerBinding(
                    "research.terminal@1",
                    "memory",
                    terminal_handler,
                    supports_origins=("controller_terminal",),
                ),
            )
        ),
        side_effect_store=store,
    )

    with pytest.raises(HarnessValidationError) as captured:
        control_plane.run(_run_spec(terminal=True))

    assert captured.value.code == "side_effect_handler_kind_mismatch"
    assert worker_calls == 0
    assert prepare_handler.call_count == 0
    assert terminal_handler.call_count == 0
    assert event_port.events == []


def test_preflight_requires_store_and_approval_resolver_before_run_creation() -> None:
    event_port = InMemoryHarnessEventPort()
    store = InMemoryHarnessSideEffectStore()
    handler = CountingHarnessSideEffectHandler(store)
    registry = HarnessSideEffectRegistry(
        (HarnessSideEffectHandlerBinding("research.prepare@1", "artifact", handler),)
    )

    without_store = HarnessControlPlane(
        event_port=event_port,
        worker_registry={"publish": _candidate_result},
        side_effect_registry=registry,
    )
    with pytest.raises(HarnessValidationError) as missing_store:
        without_store.run(_run_spec())

    without_resolver = HarnessControlPlane(
        event_port=event_port,
        worker_registry={"publish": _candidate_result},
        side_effect_registry=registry,
        side_effect_store=store,
    )
    with pytest.raises(HarnessValidationError) as missing_resolver:
        without_resolver.run(_run_spec(approval_required=True))

    assert missing_store.value.code == "side_effect_store_missing"
    assert missing_resolver.value.code == "side_effect_approval_resolver_missing"
    assert handler.call_count == 0
    assert event_port.events == []


def test_gate_failure_never_calls_side_effect_handler() -> None:
    store = InMemoryHarnessSideEffectStore()
    handler = _EffectSurfaceProbe(store)
    worker_calls = 0

    def worker(task: dict) -> HarnessWorkerResult:
        nonlocal worker_calls
        worker_calls += 1
        return _candidate_result(task)

    control_plane = HarnessControlPlane(
        event_port=InMemoryHarnessEventPort(),
        worker_registry={"publish": worker},
        verify_gates=(_FailGate(),),
        side_effect_registry=HarnessSideEffectRegistry(
            (HarnessSideEffectHandlerBinding("research.prepare@1", "artifact", handler),)
        ),
        side_effect_store=store,
    )

    result = control_plane.run(_run_spec())

    assert result.state.status is HarnessRunStatus.HALTED
    assert worker_calls == 1
    assert handler.call_count == 0
    assert handler.counts.snapshot() == (0, 0, 0, 0, 0)
    assert store.decision_write_count == 0
    assert store.outcome_write_count == 0


def test_authorization_and_outcome_precede_step_success() -> None:
    event_port = InMemoryHarnessEventPort()
    store = InMemoryHarnessSideEffectStore()
    handler = CountingHarnessSideEffectHandler(store)
    control_plane = HarnessControlPlane(
        event_port=event_port,
        worker_registry={"publish": _candidate_result},
        side_effect_registry=HarnessSideEffectRegistry(
            (HarnessSideEffectHandlerBinding("research.prepare@1", "artifact", handler),)
        ),
        side_effect_store=store,
    )

    result = control_plane.run(_run_spec())

    assert result.succeeded
    assert handler.call_count == 1
    assert store.decision_write_count == 1
    assert store.outcome_write_count == 1
    outcome = result.side_effect_outcomes["publish"]
    assert outcome.disposition.value == "prepared"
    step = result.state.step_states[0]
    assert step.metadata["side_effect_decision_ref"] == outcome.decision_ref
    assert step.metadata["side_effect_outcome_ref"] == outcome.checksum
    authorization = store.list_decisions(run_id=result.state.run_spec.run_id)[0]
    _assert_graph_side_effect_commit_order(
        event_port,
        run_id=result.state.run_spec.run_id,
        authorization=authorization,
        outcome=outcome,
    )
    assert authorization.checksum == outcome.decision_ref


def test_controller_terminal_handler_commits_before_run_success() -> None:
    store = InMemoryHarnessSideEffectStore()
    prepare_handler = CountingHarnessSideEffectHandler(store)
    terminal_handler = CountingHarnessSideEffectHandler(store, disposition="accepted")
    registry = HarnessSideEffectRegistry(
        (
            HarnessSideEffectHandlerBinding("research.prepare@1", "artifact", prepare_handler),
            HarnessSideEffectHandlerBinding(
                "research.terminal@1",
                "artifact",
                terminal_handler,
                supports_origins=("controller_terminal",),
            ),
        )
    )
    control_plane = HarnessControlPlane(
        event_port=InMemoryHarnessEventPort(),
        worker_registry={"publish": _candidate_result},
        side_effect_registry=registry,
        side_effect_store=store,
    )

    result = control_plane.run(_run_spec(terminal=True))

    assert result.succeeded
    assert prepare_handler.effect_count == 1
    assert terminal_handler.effect_count == 1
    assert result.side_effect_outcomes["__terminal__"].disposition.value == "accepted"
    assert result.state.metadata["terminal_side_effect_outcome_ref"] == result.side_effect_outcomes[
        "__terminal__"
    ].checksum


def test_budget_halt_never_calls_candidate_worker_or_side_effect_handler() -> None:
    store = InMemoryHarnessSideEffectStore()
    handler = _EffectSurfaceProbe(store)
    worker_calls = 0

    def worker(task: dict) -> HarnessWorkerResult:
        nonlocal worker_calls
        worker_calls += 1
        return _candidate_result(task)

    result = HarnessControlPlane(
        event_port=InMemoryHarnessEventPort(),
        worker_registry={"publish": worker},
        side_effect_registry=HarnessSideEffectRegistry(
            (HarnessSideEffectHandlerBinding("research.prepare@1", "artifact", handler),)
        ),
        side_effect_store=store,
    ).run(_run_spec(max_turns=1))

    assert result.state.status is HarnessRunStatus.HALTED
    assert worker_calls == 0
    assert handler.call_count == 0
    assert handler.counts.snapshot() == (0, 0, 0, 0, 0)
    assert store.decision_write_count == 0
    assert store.outcome_write_count == 0


def test_approval_wait_and_cancel_never_call_side_effect_handler() -> None:
    store = InMemoryHarnessSideEffectStore()
    handler = _EffectSurfaceProbe(store)
    event_port = InMemoryHarnessEventPort()
    worker_calls = 0

    def worker(task: dict) -> HarnessWorkerResult:
        nonlocal worker_calls
        worker_calls += 1
        return _candidate_result(task)

    control_plane = HarnessControlPlane(
        event_port=event_port,
        worker_registry={"publish": worker},
        side_effect_registry=HarnessSideEffectRegistry(
            (HarnessSideEffectHandlerBinding("research.prepare@1", "artifact", handler),)
        ),
        side_effect_store=store,
        approval_evidence_resolver=InMemoryHarnessSideEffectApprovalResolver(),
    )
    run_spec = _run_spec(approval_required=True)

    waiting = control_plane.run(run_spec)
    cancelled = control_plane.resume_after_approval(run_spec, approved=False)

    assert waiting.state.status is HarnessRunStatus.WAITING_APPROVAL
    assert cancelled.state.status is HarnessRunStatus.CANCELLED
    assert worker_calls == 1
    assert handler.call_count == 0
    assert handler.counts.snapshot() == (0, 0, 0, 0, 0)
    assert store.decision_write_count == 0
    assert store.outcome_write_count == 0


def test_worker_retry_uses_a_new_attempt_and_commits_only_the_successful_candidate() -> None:
    store = InMemoryHarnessSideEffectStore()
    handler = _EffectSurfaceProbe(store)
    attempts: list[int] = []

    def worker(task: dict) -> HarnessWorkerResult:
        attempt = task["harness_activity"]["attempt"]
        attempts.append(attempt)
        if attempt == 1:
            return HarnessWorkerResult(status="failed", error="retryable")
        return _candidate_result(task)

    result = HarnessControlPlane(
        event_port=InMemoryHarnessEventPort(),
        worker_registry={"publish": worker},
        side_effect_registry=HarnessSideEffectRegistry(
            (HarnessSideEffectHandlerBinding("research.prepare@1", "artifact", handler),)
        ),
        side_effect_store=store,
    ).run(_run_spec(effect_attempt_limit=2))

    assert result.succeeded
    assert attempts == [1, 2]
    assert handler.call_count == 1
    assert handler.counts.snapshot() == (1, 1, 1, 1, 1)
    assert tuple(store.outcomes_by_effect) == ("effect-2",)
    assert store.decision_write_count == 1


def test_replan_uses_a_new_attempt_and_does_not_commit_the_rejected_candidate() -> None:
    store = InMemoryHarnessSideEffectStore()
    handler = _EffectSurfaceProbe(store)
    gate = _FailOnceGate()
    attempts: list[int] = []

    def worker(task: dict) -> HarnessWorkerResult:
        attempts.append(task["harness_activity"]["attempt"])
        return _candidate_result(task)

    result = HarnessControlPlane(
        event_port=InMemoryHarnessEventPort(),
        worker_registry={"publish": worker},
        verify_gates=(gate,),
        side_effect_registry=HarnessSideEffectRegistry(
            (HarnessSideEffectHandlerBinding("research.prepare@1", "artifact", handler),)
        ),
        side_effect_store=store,
    ).run(_run_spec(effect_attempt_limit=2, max_replans=1))

    assert result.succeeded
    assert attempts == [1, 2]
    assert gate.call_count == 2
    assert handler.call_count == 1
    assert handler.counts.snapshot() == (1, 1, 1, 1, 1)
    assert tuple(store.outcomes_by_effect) == ("effect-2",)


def test_scope_mismatch_never_authorizes_or_calls_the_handler() -> None:
    store = InMemoryHarnessSideEffectStore()
    handler = CountingHarnessSideEffectHandler(store)

    def worker(task: dict) -> HarnessWorkerResult:
        candidate = _candidate_result(task)
        assert candidate.effect_intent is not None
        mismatched = replace(
            candidate.effect_intent,
            identity_scope_ref=checksum_for({"tenant_id": "tenant-2"}),
            checksum=None,
        )
        return replace(candidate, effect_intent=mismatched)

    control_plane = HarnessControlPlane(
        event_port=InMemoryHarnessEventPort(),
        worker_registry={"publish": worker},
        side_effect_registry=HarnessSideEffectRegistry(
            (HarnessSideEffectHandlerBinding("research.prepare@1", "artifact", handler),)
        ),
        side_effect_store=store,
    )

    with pytest.raises(HarnessValidationError) as captured:
        control_plane.run(_run_spec())

    assert captured.value.code == "side_effect_scope_mismatch"
    assert handler.call_count == 0
    assert store.decision_write_count == 0
    assert store.outcome_write_count == 0


def test_worker_cannot_supply_a_controller_terminal_intent() -> None:
    store = InMemoryHarnessSideEffectStore()
    handler = CountingHarnessSideEffectHandler(store)

    def worker(task: dict) -> HarnessWorkerResult:
        return HarnessWorkerResult(
            status="succeeded",
            output={"candidate": "ok"},
            effect_intent=HarnessSideEffectIntent(
                effect_id="forged-terminal-effect",
                kind="artifact",
                run_id=task["run_id"],
                origin="controller_terminal",
                atomic_group="research-run-1",
                identity_scope_ref=IDENTITY_SCOPE_REF,
                subject_scope_ref=SUBJECT_SCOPE_REF,
                terminal_action="complete_run",
                state_checksum=checksum_for({"state": "forged"}),
                completion_input_ref=checksum_for({"input": "forged"}),
                handler="research.prepare@1",
            ),
        )

    control_plane = HarnessControlPlane(
        event_port=InMemoryHarnessEventPort(),
        worker_registry={"publish": worker},
        side_effect_registry=HarnessSideEffectRegistry(
            (HarnessSideEffectHandlerBinding("research.prepare@1", "artifact", handler),)
        ),
        side_effect_store=store,
    )

    with pytest.raises(HarnessValidationError) as captured:
        control_plane.run(_run_spec())

    assert captured.value.code == "side_effect_intent_identity_mismatch"
    assert handler.call_count == 0
    assert store.decision_write_count == 0
    assert store.outcome_write_count == 0


def test_crash_before_authorization_reuses_worker_result_without_early_effect() -> None:
    event_port = InMemoryHarnessEventPort()
    store = _FailBeforeAuthorizationStore()
    handler = CountingHarnessSideEffectHandler(store)
    registry = HarnessSideEffectRegistry(
        (HarnessSideEffectHandlerBinding("research.prepare@1", "artifact", handler),)
    )
    run_spec = _run_spec()
    worker_calls = 0

    def worker(task: dict) -> HarnessWorkerResult:
        nonlocal worker_calls
        worker_calls += 1
        return _candidate_result(task)

    with pytest.raises(RuntimeError, match="before side-effect authorization"):
        HarnessControlPlane(
            event_port=event_port,
            worker_registry={"publish": worker},
            side_effect_registry=registry,
            side_effect_store=store,
        ).run(run_spec)

    assert worker_calls == 1
    assert handler.call_count == 0
    assert store.decision_write_count == 0
    assert store.outcome_write_count == 0
    assert all(
        commit.decision.decision_type is not HarnessGraphDecisionType.COMPLETE_NODE
        for commit in event_port.recover_graph(run_spec.run_id).decision_commits
    )

    recovered = HarnessControlPlane(
        event_port=event_port,
        worker_registry={"publish": worker},
        side_effect_registry=registry,
        side_effect_store=store,
    ).recover_and_run(run_spec)

    assert recovered.succeeded
    assert worker_calls == 1
    assert handler.call_count == 1
    assert store.decision_write_count == 1
    assert store.outcome_write_count == 1


def test_recovery_reuses_durable_authorization_identity() -> None:
    event_port = InMemoryHarnessEventPort()
    store = _FailAfterAuthorizationStore()
    handler = CountingHarnessSideEffectHandler(store)
    registry = HarnessSideEffectRegistry(
        (HarnessSideEffectHandlerBinding("research.prepare@1", "artifact", handler),)
    )
    run_spec = _run_spec()
    worker_calls = 0

    def worker(task: dict) -> HarnessWorkerResult:
        nonlocal worker_calls
        worker_calls += 1
        return _candidate_result(task)

    with pytest.raises(RuntimeError, match="after side-effect authorization"):
        HarnessControlPlane(
            event_port=event_port,
            worker_registry={"publish": worker},
            side_effect_registry=registry,
            side_effect_store=store,
        ).run(run_spec)

    original = store.list_decisions(run_id=run_spec.run_id)[0]
    assert worker_calls == 1
    assert handler.call_count == 0
    assert store.decision_write_count == 1
    assert store.outcome_write_count == 0
    assert all(
        commit.decision.decision_type is not HarnessGraphDecisionType.COMPLETE_NODE
        for commit in event_port.recover_graph(run_spec.run_id).decision_commits
    )

    result = HarnessControlPlane(
        event_port=event_port,
        worker_registry={"publish": worker},
        side_effect_registry=registry,
        side_effect_store=store,
    ).recover_and_run(run_spec)
    authorization = store.list_decisions(run_id=run_spec.run_id)[0]
    outcome = result.side_effect_outcomes["publish"]

    assert result.succeeded
    assert worker_calls == 1
    assert handler.call_count == 1
    assert authorization == original
    _assert_graph_side_effect_commit_order(
        event_port,
        run_id=run_spec.run_id,
        authorization=authorization,
        outcome=outcome,
    )


def test_recovery_reuses_external_effect_identity_after_crash_before_outcome() -> None:
    event_port = InMemoryHarnessEventPort()
    store = InMemoryHarnessSideEffectStore()
    handler = _EffectThenRecoverHandler(store)
    registry = HarnessSideEffectRegistry(
        (HarnessSideEffectHandlerBinding("research.prepare@1", "artifact", handler),)
    )
    run_spec = _run_spec(effect_attempt_limit=2)

    with pytest.raises(RuntimeError, match="after external effect"):
        HarnessControlPlane(
            event_port=event_port,
            worker_registry={"publish": _candidate_result},
            side_effect_registry=registry,
            side_effect_store=store,
        ).run(run_spec)

    result = HarnessControlPlane(
        event_port=event_port,
        worker_registry={"publish": _candidate_result},
        side_effect_registry=registry,
        side_effect_store=store,
    ).recover_and_run(run_spec)

    assert result.succeeded
    assert handler.call_count == 2
    assert handler.external_effect_ids == {"effect-1"}
    assert store.attempts_by_effect == {"effect-1": 2}
    assert store.outcome_write_count == 1


def test_recovery_reuses_durable_outcome_after_crash_before_step_transition() -> None:
    event_port = _FailBeforeGraphProjectionPort(
        HarnessGraphDecisionType.COMPLETE_NODE
    )
    store = InMemoryHarnessSideEffectStore()
    handler = CountingHarnessSideEffectHandler(store)
    registry = HarnessSideEffectRegistry(
        (HarnessSideEffectHandlerBinding("research.prepare@1", "artifact", handler),)
    )
    run_spec = _run_spec()

    with pytest.raises(RuntimeError, match="before complete_node projection"):
        HarnessControlPlane(
            event_port=event_port,
            worker_registry={"publish": _candidate_result},
            side_effect_registry=registry,
            side_effect_store=store,
        ).run(run_spec)

    result = HarnessControlPlane(
        event_port=event_port,
        worker_registry={"publish": _candidate_result},
        side_effect_registry=registry,
        side_effect_store=store,
    ).recover_and_run(run_spec)

    assert result.succeeded
    assert handler.call_count == 1
    assert store.decision_write_count == 1
    assert store.outcome_write_count == 1
    assert store.attempts_by_effect == {"effect-1": 1}


def test_terminal_recovery_reuses_durable_outcome_before_run_success() -> None:
    event_port = _FailBeforeGraphProjectionPort(
        HarnessGraphDecisionType.COMPLETE_RUN
    )
    store = InMemoryHarnessSideEffectStore()
    prepare_handler = CountingHarnessSideEffectHandler(store)
    terminal_handler = CountingHarnessSideEffectHandler(store, disposition="accepted")
    registry = HarnessSideEffectRegistry(
        (
            HarnessSideEffectHandlerBinding("research.prepare@1", "artifact", prepare_handler),
            HarnessSideEffectHandlerBinding(
                "research.terminal@1",
                "artifact",
                terminal_handler,
                supports_origins=("controller_terminal",),
            ),
        )
    )
    run_spec = _run_spec(terminal=True)

    with pytest.raises(RuntimeError, match="before complete_run projection"):
        HarnessControlPlane(
            event_port=event_port,
            worker_registry={"publish": _candidate_result},
            side_effect_registry=registry,
            side_effect_store=store,
        ).run(run_spec)

    result = HarnessControlPlane(
        event_port=event_port,
        worker_registry={"publish": _candidate_result},
        side_effect_registry=registry,
        side_effect_store=store,
    ).recover_and_run(run_spec)

    assert result.succeeded
    assert prepare_handler.call_count == 1
    assert terminal_handler.call_count == 1
    assert result.side_effect_outcomes["__terminal__"].disposition.value == "accepted"


def _assert_graph_side_effect_retry_exhaustion(recovery, authorization) -> None:
    failure_commits = tuple(
        commit
        for commit in recovery.observation_commits
        if commit.observation.observation_type
        is HarnessGraphObservationType.SIDE_EFFECT_FAILURE
    )
    assert len(failure_commits) == 1
    failure_commit = failure_commits[0]
    failure = failure_commit.observation
    expected_failure_ref = checksum_for(
        {
            "code": "effect_retry_exhausted",
            "effect_ref": checksum_for(authorization.effect_id),
            "decision_ref": authorization.checksum,
        }
    )

    assert failure.contract_ref.exact_ref == str(authorization.handler)
    assert failure.payload["reason_code"] == "effect_retry_exhausted"
    assert failure.payload["decision_ref"] == authorization.checksum
    assert failure.payload["causal_graph_decision_checksum"] == (
        authorization.causation_id
    )
    assert failure.payload["failure_ref"] == failure.evidence_ref
    assert failure.evidence_ref == expected_failure_ref

    terminal_commits = tuple(
        commit
        for commit in recovery.decision_commits
        if commit.decision.decision_type is HarnessGraphDecisionType.COMPLETE_RUN
        and commit.decision.reason_code == "side_effect_retry_exhausted"
    )
    assert len(terminal_commits) == 1
    terminal = terminal_commits[0]
    assert terminal.decision.payload["outcome"] == "failed"
    assert terminal.decision.evidence_refs == (failure.evidence_ref,)
    assert terminal.accepted_evidence_refs == terminal.decision.evidence_refs
    assert terminal.side_effect_outcome_ref is None
    assert terminal.sequence == failure_commit.sequence + 2


def test_effect_retry_exhaustion_records_one_stable_failed_terminal_state() -> None:
    event_port = InMemoryHarnessEventPort()
    store = InMemoryHarnessSideEffectStore()
    handler = CountingHarnessSideEffectHandler(store, fail_before_outcome=True)
    registry = HarnessSideEffectRegistry(
        (HarnessSideEffectHandlerBinding("research.prepare@1", "artifact", handler),)
    )
    run_spec = _run_spec()

    with pytest.raises(RuntimeError, match="handler failure"):
        HarnessControlPlane(
            event_port=event_port,
            worker_registry={"publish": _candidate_result},
            side_effect_registry=registry,
            side_effect_store=store,
        ).run(run_spec)

    recovered = HarnessControlPlane(
        event_port=event_port,
        worker_registry={"publish": _candidate_result},
        side_effect_registry=registry,
        side_effect_store=store,
    ).recover_and_run(run_spec)
    recovery_after_failure = event_port.recover_graph(run_spec.run_id)
    replayed = HarnessControlPlane(
        event_port=event_port,
        worker_registry={"publish": _candidate_result},
        side_effect_registry=registry,
        side_effect_store=store,
    ).recover_and_run(run_spec)
    replayed_recovery = event_port.recover_graph(run_spec.run_id)
    authorization = store.list_decisions(run_id=run_spec.run_id)[0]

    assert recovered.state.status is HarnessRunStatus.FAILED
    assert replayed.state.status is HarnessRunStatus.FAILED
    assert (
        recovered.state.metadata["terminal_reason"]
        == "side-effect failure: effect_retry_exhausted"
    )
    assert handler.call_count == 1
    assert store.attempts_by_effect == {"effect-1": 1}
    _assert_graph_side_effect_retry_exhaustion(
        replayed_recovery,
        authorization,
    )
    assert replayed_recovery.observation_commits == (
        recovery_after_failure.observation_commits
    )
    assert replayed_recovery.decision_commits == (
        recovery_after_failure.decision_commits
    )
    assert replayed_recovery.projection_commits == (
        recovery_after_failure.projection_commits
    )


def test_terminal_retry_exhaustion_is_persisted_and_stable() -> None:
    event_port = InMemoryHarnessEventPort()
    store = InMemoryHarnessSideEffectStore()
    prepare_handler = CountingHarnessSideEffectHandler(store)
    terminal_handler = CountingHarnessSideEffectHandler(
        store,
        disposition="accepted",
        fail_before_outcome=True,
    )
    registry = HarnessSideEffectRegistry(
        (
            HarnessSideEffectHandlerBinding(
                "research.prepare@1", "artifact", prepare_handler
            ),
            HarnessSideEffectHandlerBinding(
                "research.terminal@1",
                "artifact",
                terminal_handler,
                supports_origins=("controller_terminal",),
            ),
        )
    )
    run_spec = _run_spec(terminal=True)

    with pytest.raises(RuntimeError, match="handler failure"):
        HarnessControlPlane(
            event_port=event_port,
            worker_registry={"publish": _candidate_result},
            side_effect_registry=registry,
            side_effect_store=store,
        ).run(run_spec)

    recovered = HarnessControlPlane(
        event_port=event_port,
        worker_registry={"publish": _candidate_result},
        side_effect_registry=registry,
        side_effect_store=store,
    ).recover_and_run(run_spec)
    recovery_after_failure = event_port.recover_graph(run_spec.run_id)
    replayed = HarnessControlPlane(
        event_port=event_port,
        worker_registry={"publish": _candidate_result},
        side_effect_registry=registry,
        side_effect_store=store,
    ).recover_and_run(run_spec)
    replayed_recovery = event_port.recover_graph(run_spec.run_id)
    terminal_decision = next(
        decision
        for decision in store.list_decisions(run_id=run_spec.run_id)
        if decision.origin.value == "controller_terminal"
    )

    assert recovered.state.status is HarnessRunStatus.FAILED
    assert replayed.state.status is HarnessRunStatus.FAILED
    assert terminal_handler.call_count == 1
    assert store.attempt_count(
        effect_id=terminal_decision.effect_id,
        identity_scope_ref=terminal_decision.identity_scope_ref,
        subject_scope_ref=terminal_decision.subject_scope_ref,
    ) == 1
    assert store.outcomes_by_effect["effect-1"].disposition.value == "quarantine"
    _assert_graph_side_effect_retry_exhaustion(
        replayed_recovery,
        terminal_decision,
    )
    assert replayed_recovery.observation_commits == (
        recovery_after_failure.observation_commits
    )
    assert replayed_recovery.decision_commits == (
        recovery_after_failure.decision_commits
    )
    assert replayed_recovery.projection_commits == (
        recovery_after_failure.projection_commits
    )
