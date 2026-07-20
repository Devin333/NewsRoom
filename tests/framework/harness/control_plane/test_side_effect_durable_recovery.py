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
from infrastructure.storage.events.activity_store import SQLiteRecordedActivityStore
from infrastructure.storage.events.sqlite import SQLiteEventStore
from infrastructure.storage.harness import SQLiteHarnessSideEffectStore


IDENTITY_SCOPE_REF = checksum_for("tenant-test")
SUBJECT_SCOPE_REF = checksum_for({"paper_id": "paper-1"})


class _FailBeforeTransitionPort:
    def __init__(self, port, transition_kind: HarnessTransitionKind) -> None:
        self._port = port
        self._transition_kind = transition_kind
        self._failed = False

    def __getattr__(self, name):
        return getattr(self._port, name)

    def commit_transition(self, previous, state, **kwargs):
        kind = HarnessTransitionKind(kwargs["transition_kind"])
        if not self._failed and kind is self._transition_kind:
            self._failed = True
            raise RuntimeError(f"injected crash before {kind.value}")
        return self._port.commit_transition(previous, state, **kwargs)


class _FailAfterCompletionDecisionPort:
    def __init__(self, port) -> None:
        self._port = port
        self._failed = False

    def __getattr__(self, name):
        return getattr(self._port, name)

    def record(self, event):
        committed = self._port.record(event)
        if (
            not self._failed
            and event.event_type.value == "decision_recorded"
            and event.payload.get("decision_type") in {"complete_step", "complete_run"}
        ):
            self._failed = True
            raise RuntimeError("injected crash after durable completion decision")
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


def test_sqlite_recovery_reuses_durable_decision_without_worker_reexecution(
    tmp_path,
) -> None:
    event_database = tmp_path / "events.sqlite3"
    effect_database = tmp_path / "side-effects.sqlite3"
    encryption_key = Fernet.generate_key()
    first_store = SQLiteHarnessSideEffectStore(effect_database)
    first_handler = CountingHarnessSideEffectHandler(first_store)
    run_spec = _run_spec()
    worker_calls = 0

    def worker(task: dict) -> HarnessWorkerResult:
        nonlocal worker_calls
        worker_calls += 1
        return _worker_result(task)

    with pytest.raises(RuntimeError, match="after durable completion decision"):
        HarnessControlPlane(
            event_port=_FailAfterCompletionDecisionPort(
                _event_port(event_database, encryption_key)
            ),
            worker_registry={"publish": worker},
            side_effect_registry=_registry(first_handler),
            side_effect_store=first_store,
        ).run(run_spec)

    assert worker_calls == 1
    assert first_handler.call_count == 0
    assert first_store.list_decisions(run_id=run_spec.run_id) == ()

    recovered_store = SQLiteHarnessSideEffectStore(effect_database)
    recovered_handler = CountingHarnessSideEffectHandler(recovered_store)
    result = HarnessControlPlane(
        event_port=_event_port(event_database, encryption_key),
        worker_registry={"publish": worker},
        side_effect_registry=_registry(recovered_handler),
        side_effect_store=recovered_store,
    ).recover_and_run(run_spec)

    assert result.succeeded
    assert worker_calls == 1
    assert recovered_handler.call_count == 1
    assert len(recovered_store.list_decisions(run_id=run_spec.run_id)) == 1


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
