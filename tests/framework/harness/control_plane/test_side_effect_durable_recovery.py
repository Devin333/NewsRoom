from __future__ import annotations

from cryptography.fernet import Fernet
import pytest

from framework.events.canonical import checksum_for
from framework.events.runtime.publisher import EventRuntime
from framework.events.schema import EventSecurityProjector, default_event_schema_catalog
from framework.harness import (
    CountingHarnessSideEffectHandler,
    DurableHarnessTransitionPort,
    HarnessBudget,
    HarnessControlPlane,
    HarnessEventCanonicalAdapter,
    HarnessGraphDecisionType,
    HarnessRetryPolicy,
    HarnessRunSpec,
    HarnessRunStatus,
    HarnessSideEffectHandlerBinding,
    HarnessSideEffectIntent,
    HarnessSideEffectRegistry,
    HarnessStepSpec,
    HarnessTerminalSideEffectPolicy,
    HarnessTransitionKind,
    HarnessWorkerResult,
    HarnessWorkflowSpec,
    harness_worker_candidate_ref,
)
from framework.harness.control_plane.graph_evaluator import HarnessGraphObservationType
from infrastructure.storage.events.activity_store import SQLiteRecordedActivityStore
from infrastructure.storage.events.sqlite import SQLiteEventStore
from infrastructure.storage.harness import SQLiteHarnessSideEffectStore


IDENTITY_SCOPE_REF = checksum_for("tenant-test")
SUBJECT_SCOPE_REF = checksum_for({"paper_id": "paper-1"})


class _GraphPortProxy:
    def __init__(self, port) -> None:
        self._port = port

    def __getattr__(self, name):
        return getattr(self._port, name)

    def initialize_graph(self, *args, **kwargs):
        return self._port.initialize_graph(*args, **kwargs)

    def commit_graph_decision(self, *args, **kwargs):
        return self._port.commit_graph_decision(*args, **kwargs)

    def commit_graph_projection(self, *args, **kwargs):
        return self._port.commit_graph_projection(*args, **kwargs)

    def commit_graph_activity_result(self, *args, **kwargs):
        return self._port.commit_graph_activity_result(*args, **kwargs)

    def commit_graph_observation(self, *args, **kwargs):
        return self._port.commit_graph_observation(*args, **kwargs)

    def recover_graph(self, *args, **kwargs):
        return self._port.recover_graph(*args, **kwargs)

    def activity_for(self, *args, **kwargs):
        return self._port.activity_for(*args, **kwargs)

    def mark_activity_dispatched(self, *args, **kwargs):
        return self._port.mark_activity_dispatched(*args, **kwargs)

    def graph_scope_metadata(self):
        return self._port.graph_scope_metadata()


class _FailBeforeTransitionPort(_GraphPortProxy):
    def __init__(self, port, transition_kind: HarnessTransitionKind) -> None:
        super().__init__(port)
        self._transition_kind = transition_kind
        self._failed = False

    def commit_graph_decision(self, decision, **kwargs):
        expected_type = {
            HarnessTransitionKind.STEP_SUCCESS: HarnessGraphDecisionType.COMPLETE_NODE,
            HarnessTransitionKind.SUCCESS: HarnessGraphDecisionType.COMPLETE_RUN,
        }.get(self._transition_kind)
        if not self._failed and decision.decision_type is expected_type:
            self._failed = True
            raise RuntimeError(
                f"injected crash before {self._transition_kind.value}"
            )
        return self._port.commit_graph_decision(decision, **kwargs)


class _FailAfterAuthorizationStore(SQLiteHarnessSideEffectStore):
    def __init__(self, database) -> None:
        super().__init__(database)
        self._failed = False

    def put_decision(self, decision):
        committed = super().put_decision(decision)
        if not self._failed:
            self._failed = True
            raise RuntimeError("injected crash after durable side-effect authorization")
        return committed


class _ExternalEffectRecoveryHandler:
    def __init__(self, store, external_effect_ids: set[str]) -> None:
        self._delegate = CountingHarnessSideEffectHandler(store)
        self._external_effect_ids = external_effect_ids
        self.call_count = 0

    def prepare(self, intent, authorization):
        self.call_count += 1
        if intent.effect_id not in self._external_effect_ids:
            self._external_effect_ids.add(intent.effect_id)
            raise RuntimeError("injected crash after external effect")
        return self._delegate.prepare(intent, authorization)

    def commit(self, intent, authorization):
        return self.prepare(intent, authorization)


def _event_port(database, encryption_key: bytes) -> DurableHarnessTransitionPort:
    store = SQLiteEventStore(database)
    activity_store = SQLiteRecordedActivityStore(
        database,
        encryption_key=encryption_key,
    )
    return DurableHarnessTransitionPort(
        EventRuntime(
            store=store,
            schema_catalog=default_event_schema_catalog(),
            security_projector=EventSecurityProjector(
                secure_payload_store=activity_store
            ),
        ),
        store,
        secure_activity_store=activity_store,
        adapter=HarnessEventCanonicalAdapter(tenant_id="tenant-test"),
    )


def _worker_result(task: dict) -> HarnessWorkerResult:
    output = {"candidate": "ok"}
    candidate_payload = {
        "status": "succeeded",
        "output": output,
        "artifacts": ["candidate://run-durable/report"],
        "diagnostics": {},
        "metrics": {},
        "error": None,
    }
    attempt = task["harness_activity"]["attempt"]
    return HarnessWorkerResult(
        status="succeeded",
        output=output,
        artifacts=("candidate://run-durable/report",),
        effect_intent=HarnessSideEffectIntent(
            effect_id=f"durable-effect-{attempt}",
            kind="artifact",
            run_id=task["run_id"],
            origin="worker",
            atomic_group="durable-run-group",
            identity_scope_ref=IDENTITY_SCOPE_REF,
            subject_scope_ref=SUBJECT_SCOPE_REF,
            attempt=attempt,
            step_id=task["step_id"],
            worker_result_ref=harness_worker_candidate_ref(candidate_payload),
            candidate_checksum=checksum_for(output),
            handler="research.prepare@1",
            candidate_refs=("candidate://run-durable/report",),
        ),
    )


def _run_spec(
    *,
    terminal: bool = False,
    effect_attempt_limit: int = 1,
) -> HarnessRunSpec:
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
    return HarnessRunSpec(
        run_id="run-durable",
        workflow=HarnessWorkflowSpec(
            workflow_id="durable-side-effect",
            steps=(
                HarnessStepSpec(
                    step_id="publish",
                    worker_type="artifact",
                    output_key="candidate",
                    retry_policy=HarnessRetryPolicy(max_attempts=effect_attempt_limit),
                    side_effect_handler="research.prepare@1",
                ),
            ),
            entry_step_id="publish",
            terminal_side_effect_policy=terminal_policy,
        ),
        metadata={
            "identity_scope_ref": IDENTITY_SCOPE_REF,
            "subject_scope_ref": SUBJECT_SCOPE_REF,
        },
        budget=HarnessBudget(
            max_turns=10,
            max_replans=0,
            max_retries_per_step=effect_attempt_limit - 1,
            max_worker_calls=2,
        ),
    )


def _registry(prepare_handler, terminal_handler=None) -> HarnessSideEffectRegistry:
    bindings = [
        HarnessSideEffectHandlerBinding(
            "research.prepare@1",
            "artifact",
            prepare_handler,
        )
    ]
    if terminal_handler is not None:
        bindings.append(
            HarnessSideEffectHandlerBinding(
                "research.terminal@1",
                "artifact",
                terminal_handler,
                supports_origins=("controller_terminal",),
            )
        )
    return HarnessSideEffectRegistry(bindings)


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


def test_sqlite_recovery_reuses_durable_authorization_without_worker_reexecution(
    tmp_path,
) -> None:
    event_database = tmp_path / "events.sqlite3"
    effect_database = tmp_path / "side-effects.sqlite3"
    encryption_key = Fernet.generate_key()
    first_store = _FailAfterAuthorizationStore(effect_database)
    first_handler = CountingHarnessSideEffectHandler(first_store)
    run_spec = _run_spec()
    worker_calls = 0

    def worker(task: dict) -> HarnessWorkerResult:
        nonlocal worker_calls
        worker_calls += 1
        return _worker_result(task)

    first_event_port = _event_port(event_database, encryption_key)
    with pytest.raises(
        RuntimeError,
        match="after durable side-effect authorization",
    ):
        HarnessControlPlane(
            event_port=first_event_port,
            worker_registry={"publish": worker},
            side_effect_registry=_registry(first_handler),
            side_effect_store=first_store,
        ).run(run_spec)

    original = first_store.list_decisions(run_id=run_spec.run_id)[0]
    assert worker_calls == 1
    assert first_handler.call_count == 0
    assert len(first_store.list_decisions(run_id=run_spec.run_id)) == 1
    assert first_store.attempt_count(
        effect_id=original.effect_id,
        identity_scope_ref=original.identity_scope_ref,
        subject_scope_ref=original.subject_scope_ref,
    ) == 0
    assert all(
        commit.decision.decision_type is not HarnessGraphDecisionType.COMPLETE_NODE
        for commit in first_event_port.recover_graph(run_spec.run_id).decision_commits
    )

    recovered_store = SQLiteHarnessSideEffectStore(effect_database)
    recovered_handler = CountingHarnessSideEffectHandler(recovered_store)
    recovered_event_port = _event_port(event_database, encryption_key)
    result = HarnessControlPlane(
        event_port=recovered_event_port,
        worker_registry={"publish": worker},
        side_effect_registry=_registry(recovered_handler),
        side_effect_store=recovered_store,
    ).recover_and_run(run_spec)
    authorization = recovered_store.list_decisions(run_id=run_spec.run_id)[0]
    outcome = result.side_effect_outcomes["publish"]

    assert result.succeeded
    assert worker_calls == 1
    assert recovered_handler.call_count == 1
    assert len(recovered_store.list_decisions(run_id=run_spec.run_id)) == 1
    assert authorization == original
    _assert_graph_side_effect_commit_order(
        recovered_event_port,
        run_id=run_spec.run_id,
        authorization=authorization,
        outcome=outcome,
    )


def test_sqlite_recovery_reuses_external_effect_identity_before_outcome(
    tmp_path,
) -> None:
    event_database = tmp_path / "events.sqlite3"
    effect_database = tmp_path / "side-effects.sqlite3"
    encryption_key = Fernet.generate_key()
    external_effect_ids: set[str] = set()
    first_store = SQLiteHarnessSideEffectStore(effect_database)
    first_handler = _ExternalEffectRecoveryHandler(first_store, external_effect_ids)
    run_spec = _run_spec(effect_attempt_limit=2)

    with pytest.raises(RuntimeError, match="after external effect"):
        HarnessControlPlane(
            event_port=_event_port(event_database, encryption_key),
            worker_registry={"publish": _worker_result},
            side_effect_registry=_registry(first_handler),
            side_effect_store=first_store,
        ).run(run_spec)

    recovered_store = SQLiteHarnessSideEffectStore(effect_database)
    recovered_handler = _ExternalEffectRecoveryHandler(
        recovered_store,
        external_effect_ids,
    )
    result = HarnessControlPlane(
        event_port=_event_port(event_database, encryption_key),
        worker_registry={"publish": _worker_result},
        side_effect_registry=_registry(recovered_handler),
        side_effect_store=recovered_store,
    ).recover_and_run(run_spec)

    assert result.succeeded
    assert first_handler.call_count == 1
    assert recovered_handler.call_count == 1
    assert external_effect_ids == {"durable-effect-1"}
    assert recovered_store.attempt_count(
        effect_id="durable-effect-1",
        identity_scope_ref=IDENTITY_SCOPE_REF,
        subject_scope_ref=SUBJECT_SCOPE_REF,
    ) == 2


def test_sqlite_recovery_reuses_durable_outcome_without_worker_or_handler_call(
    tmp_path,
) -> None:
    event_database = tmp_path / "events.sqlite3"
    effect_database = tmp_path / "side-effects.sqlite3"
    encryption_key = Fernet.generate_key()
    first_store = SQLiteHarnessSideEffectStore(effect_database)
    first_handler = CountingHarnessSideEffectHandler(first_store)
    run_spec = _run_spec()

    with pytest.raises(RuntimeError, match="before step_success"):
        HarnessControlPlane(
            event_port=_FailBeforeTransitionPort(
                _event_port(event_database, encryption_key),
                HarnessTransitionKind.STEP_SUCCESS,
            ),
            worker_registry={"publish": _worker_result},
            side_effect_registry=_registry(first_handler),
            side_effect_store=first_store,
        ).run(run_spec)

    worker_calls = 0

    def unexpected_worker(task: dict) -> HarnessWorkerResult:
        nonlocal worker_calls
        worker_calls += 1
        return _worker_result(task)

    recovered_store = SQLiteHarnessSideEffectStore(effect_database)
    recovered_handler = CountingHarnessSideEffectHandler(recovered_store)
    result = HarnessControlPlane(
        event_port=_event_port(event_database, encryption_key),
        worker_registry={"publish": unexpected_worker},
        side_effect_registry=_registry(recovered_handler),
        side_effect_store=recovered_store,
    ).recover_and_run(run_spec)

    assert result.succeeded
    assert worker_calls == 0
    assert recovered_handler.call_count == 0
    assert recovered_store.attempt_count(
        effect_id="durable-effect-1",
        identity_scope_ref=IDENTITY_SCOPE_REF,
        subject_scope_ref=SUBJECT_SCOPE_REF,
    ) == 1


def test_sqlite_effect_retry_exhaustion_becomes_stable_failed_state_after_restart(
    tmp_path,
) -> None:
    event_database = tmp_path / "events.sqlite3"
    effect_database = tmp_path / "side-effects.sqlite3"
    encryption_key = Fernet.generate_key()
    first_store = SQLiteHarnessSideEffectStore(effect_database)
    first_handler = CountingHarnessSideEffectHandler(
        first_store,
        fail_before_outcome=True,
    )
    run_spec = _run_spec()

    with pytest.raises(RuntimeError, match="handler failure"):
        HarnessControlPlane(
            event_port=_event_port(event_database, encryption_key),
            worker_registry={"publish": _worker_result},
            side_effect_registry=_registry(first_handler),
            side_effect_store=first_store,
        ).run(run_spec)

    recovered_store = SQLiteHarnessSideEffectStore(effect_database)
    recovered_handler = CountingHarnessSideEffectHandler(
        recovered_store,
        fail_before_outcome=True,
    )
    recovered = HarnessControlPlane(
        event_port=_event_port(event_database, encryption_key),
        worker_registry={"publish": _worker_result},
        side_effect_registry=_registry(recovered_handler),
        side_effect_store=recovered_store,
    ).recover_and_run(run_spec)
    replayed = HarnessControlPlane(
        event_port=_event_port(event_database, encryption_key),
        worker_registry={"publish": _worker_result},
        side_effect_registry=_registry(recovered_handler),
        side_effect_store=SQLiteHarnessSideEffectStore(effect_database),
    ).recover_and_run(run_spec)

    assert recovered.state.status is HarnessRunStatus.FAILED
    assert replayed.state.status is HarnessRunStatus.FAILED
    assert recovered_handler.call_count == 0
    assert recovered_store.attempt_count(
        effect_id="durable-effect-1",
        identity_scope_ref=IDENTITY_SCOPE_REF,
        subject_scope_ref=SUBJECT_SCOPE_REF,
    ) == 1


def test_sqlite_terminal_retry_exhaustion_is_stable_after_restart(
    tmp_path,
) -> None:
    event_database = tmp_path / "events.sqlite3"
    effect_database = tmp_path / "side-effects.sqlite3"
    encryption_key = Fernet.generate_key()
    first_store = SQLiteHarnessSideEffectStore(effect_database)
    first_prepare = CountingHarnessSideEffectHandler(first_store)
    first_terminal = CountingHarnessSideEffectHandler(
        first_store,
        disposition="accepted",
        fail_before_outcome=True,
    )
    run_spec = _run_spec(terminal=True)

    with pytest.raises(RuntimeError, match="handler failure"):
        HarnessControlPlane(
            event_port=_event_port(event_database, encryption_key),
            worker_registry={"publish": _worker_result},
            side_effect_registry=_registry(first_prepare, first_terminal),
            side_effect_store=first_store,
        ).run(run_spec)

    recovered_store = SQLiteHarnessSideEffectStore(effect_database)
    recovered_terminal = CountingHarnessSideEffectHandler(
        recovered_store,
        disposition="accepted",
        fail_before_outcome=True,
    )
    recovered = HarnessControlPlane(
        event_port=_event_port(event_database, encryption_key),
        worker_registry={"publish": _worker_result},
        side_effect_registry=_registry(
            CountingHarnessSideEffectHandler(recovered_store),
            recovered_terminal,
        ),
        side_effect_store=recovered_store,
    ).recover_and_run(run_spec)
    replayed_store = SQLiteHarnessSideEffectStore(effect_database)
    replayed_terminal = CountingHarnessSideEffectHandler(
        replayed_store,
        disposition="accepted",
        fail_before_outcome=True,
    )
    replayed = HarnessControlPlane(
        event_port=_event_port(event_database, encryption_key),
        worker_registry={"publish": _worker_result},
        side_effect_registry=_registry(
            CountingHarnessSideEffectHandler(replayed_store),
            replayed_terminal,
        ),
        side_effect_store=replayed_store,
    ).recover_and_run(run_spec)
    terminal_decision = next(
        decision
        for decision in recovered_store.list_decisions(run_id=run_spec.run_id)
        if decision.origin.value == "controller_terminal"
    )

    assert recovered.state.status is HarnessRunStatus.FAILED
    assert replayed.state.status is HarnessRunStatus.FAILED
    assert first_terminal.call_count == 1
    assert recovered_terminal.call_count == 0
    assert replayed_terminal.call_count == 0
    assert recovered_store.attempt_count(
        effect_id=terminal_decision.effect_id,
        identity_scope_ref=terminal_decision.identity_scope_ref,
        subject_scope_ref=terminal_decision.subject_scope_ref,
    ) == 1


def test_sqlite_terminal_recovery_reuses_publication_outcome_before_run_success(
    tmp_path,
) -> None:
    event_database = tmp_path / "events.sqlite3"
    effect_database = tmp_path / "side-effects.sqlite3"
    encryption_key = Fernet.generate_key()
    first_store = SQLiteHarnessSideEffectStore(effect_database)
    first_prepare = CountingHarnessSideEffectHandler(first_store)
    first_terminal = CountingHarnessSideEffectHandler(
        first_store,
        disposition="accepted",
    )
    run_spec = _run_spec(terminal=True)

    with pytest.raises(RuntimeError, match="before success"):
        HarnessControlPlane(
            event_port=_FailBeforeTransitionPort(
                _event_port(event_database, encryption_key),
                HarnessTransitionKind.SUCCESS,
            ),
            worker_registry={"publish": _worker_result},
            side_effect_registry=_registry(first_prepare, first_terminal),
            side_effect_store=first_store,
        ).run(run_spec)

    recovered_store = SQLiteHarnessSideEffectStore(effect_database)
    recovered_prepare = CountingHarnessSideEffectHandler(recovered_store)
    recovered_terminal = CountingHarnessSideEffectHandler(
        recovered_store,
        disposition="accepted",
    )
    result = HarnessControlPlane(
        event_port=_event_port(event_database, encryption_key),
        worker_registry={"publish": _worker_result},
        side_effect_registry=_registry(recovered_prepare, recovered_terminal),
        side_effect_store=recovered_store,
    ).recover_and_run(run_spec)

    assert result.succeeded
    assert recovered_prepare.call_count == 0
    assert recovered_terminal.call_count == 0
    assert result.side_effect_outcomes["__terminal__"].disposition.value == "accepted"
