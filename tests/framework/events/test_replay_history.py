from __future__ import annotations

import ast
import os
from collections.abc import Mapping
from dataclasses import FrozenInstanceError, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from framework.events.canonical import PayloadReference, checksum_for
from framework.events.runtime.activities import (
    RecordedActivityResolver,
    ReplayActivityDescriptor,
    ReplayActivityHandlerVersion,
    ReplayActivityKind,
    ReplayActivityOutcome,
    ReplayActivityRecord,
    ReplayActivityRegistry,
    ReplayActivityStatus,
    ResolvedReplayActivity,
)
from framework.events.runtime.history import (
    CanonicalDeterministicCommand,
    CommandMismatchKind,
    DeterministicHistoryRecord,
    ExactVersionRegistration,
    ExactVersionRegistry,
    HistoryCommandMismatchError,
    HistoryCorruptionError,
    HistoryEventPolicy,
    HistoryIncompatibleVersionError,
    HistoryMissingActivityError,
    HistoryVerificationState,
    HistoryVerifier,
    RecordedCommandComparator,
)
from framework.events.runtime.replay_engine import ReplayEvent
from framework.events.schema.security import SecurityClassification


ROOT = Path(__file__).resolve().parents[3]
ACCEPTED_AT = datetime(2026, 7, 16, 8, 0, tzinfo=UTC)
ACTIVITY_CONTRACT_VERSION = "newsroom.activity/v1"
ACTIVITY_HANDLER_VERSION = "activity/v1"


def _ref(value: str) -> str:
    return checksum_for(value)


def _event(
    sequence: int = 1,
    *,
    recorded: tuple[CanonicalDeterministicCommand, ...] | None = None,
    policy: HistoryEventPolicy | None = None,
    handler_input: Mapping[str, Any] | None = None,
) -> ReplayEvent:
    history = DeterministicHistoryRecord(
        policy=policy or _policy(),
        commands=(_command(0),) if recorded is None else recorded,
        handler_input=handler_input or {},
    )
    return ReplayEvent(
        event_id=f"event-{sequence}",
        event_type="workflow.transition",
        source_data_schema="io.newsroom.workflow-transition/v1",
        data_schema="io.newsroom.workflow-transition/v2",
        stream_id="run:history-test",
        stream_sequence=sequence,
        occurred_at="2026-07-16T00:00:00Z",
        payload={"value": sequence},
        record_checksum=_ref(f"record-{sequence}"),
        history=history.to_dict(),
        applied_upcasters=(
            "io.newsroom.workflow-transition/v1"
            "->io.newsroom.workflow-transition/v2",
        ),
    )


def _command(
    ordinal: int,
    *,
    kind: str = "schedule_activity",
    target: str = "summarizer",
    handler_version: str = "handler/v1",
    graph_version: str = "workflow/v1",
    policy_version: str = "policy/v1",
    decision_ref: str | None = None,
) -> CanonicalDeterministicCommand:
    return CanonicalDeterministicCommand(
        ordinal=ordinal,
        kind=kind,
        target=target,
        handler_version=handler_version,
        graph_version=graph_version,
        policy_version=policy_version,
        input_refs=("input://accepted/1",),
        input_checksums=(_ref("input-1"),),
        budget_ref=_ref("budget-1"),
        gate_ref=_ref("gate-1"),
        decision_ref=decision_ref,
        causation_id="event-cause",
    )


def _input_driven_handler(
    event: ReplayEvent,
    handler_input: Mapping[str, Any],
    _activity_result: ResolvedReplayActivity | None,
) -> tuple[CanonicalDeterministicCommand, ...]:
    target = (
        "recorded-history-was-visible"
        if event.history is not None
        else str(handler_input["target"])
    )
    return (
        CanonicalDeterministicCommand(
            ordinal=0,
            kind="schedule_activity",
            target=target,
            handler_version="handler/v1",
            graph_version="workflow/v1",
            policy_version="policy/v1",
            input_refs=("input://accepted/1",),
            input_checksums=(
                "sha256:a1fba7f471dcad49649158d8a33a94a4cb64ccb91d8c9456fa7be307e92e8879",
            ),
            budget_ref=(
                "sha256:8a763c64b6b0dd2db46ec35c76d590035292f8eda5f1f1f1e7c6d5a19d87d456"
            ),
            gate_ref=(
                "sha256:5dc035e3ead1d4ef86038f406d7de0da0e0132f797d129b9d8b30ef36a830395"
            ),
            causation_id="event-cause",
        ),
    )


def _handler_for(
    commands: tuple[CanonicalDeterministicCommand, ...],
    *,
    require_activity: bool = False,
):
    def handler(
        _event: ReplayEvent,
        _handler_input: Mapping[str, Any],
        activity_result: ResolvedReplayActivity | None,
    ) -> tuple[CanonicalDeterministicCommand, ...]:
        if require_activity and activity_result is None:
            return ()
        return commands

    return handler


def _registry(handler) -> ExactVersionRegistry:
    registry = ExactVersionRegistry()
    for kind, component_id, version, value in (
        ("graph", "paper-analysis", "graph/v1", "pinned"),
        ("policy", "harness-policy", "policy/v1", "pinned"),
        (
            "schema",
            "io.newsroom.workflow-transition",
            "io.newsroom.workflow-transition/v2",
            "pinned",
        ),
        ("reducer", "transition-handler", "handler/v1", handler),
        ("activity_handler", "llm", "activity/v1", "pinned"),
    ):
        registry.register(
            ExactVersionRegistration(
                component_kind=kind,
                component_id=component_id,
                version=version,
                handler=value,
            )
        )
    return registry


class _ActivityStore:
    def __init__(self, value: ReplayActivityRecord | None) -> None:
        self.value = value

    def get_record(
        self,
        _recorded_ref: PayloadReference,
        *,
        tenant_id: str | None,
    ) -> ReplayActivityRecord | None:
        assert tenant_id == "tenant-a"
        return self.value


def _payload_ref(name: str, value: Any) -> PayloadReference:
    return PayloadReference(
        uri=f"secure-activity://tenant-a/{name}",
        expected_checksum=checksum_for(value),
        content_type="application/json",
        size_bytes=100,
    )


def _activity_material() -> tuple[
    ReplayActivityDescriptor,
    ReplayActivityRecord,
    PayloadReference,
]:
    input_ref = _payload_ref("input", {"prompt": "accepted"})
    activity = ReplayActivityDescriptor(
        activity_id="activity-1",
        activity_kind=ReplayActivityKind.LLM,
        input_ref=input_ref,
        input_checksum=input_ref.expected_checksum,
        idempotency_key="idempotency:activity-1",
        attempt=1,
        contract_version=ACTIVITY_CONTRACT_VERSION,
        handler_version=ACTIVITY_HANDLER_VERSION,
        accepted_at=ACCEPTED_AT,
        tenant_id="tenant-a",
        security_classification=SecurityClassification.CONFIDENTIAL,
    )
    output_ref = _payload_ref("output", {"answer": "recorded"})
    outcome = ReplayActivityOutcome(
        activity_id=activity.activity_id,
        status=ReplayActivityStatus.SUCCEEDED,
        started_at=ACCEPTED_AT + timedelta(seconds=1),
        completed_at=ACCEPTED_AT + timedelta(seconds=2),
        output_ref=output_ref,
        output_checksum=output_ref.expected_checksum,
    )
    record = ReplayActivityRecord(activity, outcome)
    record_ref = PayloadReference(
        uri="secure-activity://tenant-a/record/activity-1",
        expected_checksum=record.record_checksum,
        content_type="application/vnd.newsroom.replay-activity-record+json",
        size_bytes=500,
    )
    return activity, record, record_ref


def _activity_resolver(
    value: ReplayActivityRecord | None,
) -> RecordedActivityResolver:
    registry = ReplayActivityRegistry()
    registry.register(
        ReplayActivityHandlerVersion(
            ReplayActivityKind.LLM,
            ACTIVITY_CONTRACT_VERSION,
            ACTIVITY_HANDLER_VERSION,
        )
    )
    return RecordedActivityResolver(_ActivityStore(value), registry)


def _policy(*, activity_required: bool = False) -> HistoryEventPolicy:
    activity, _record, record_ref = _activity_material()
    return HistoryEventPolicy(
        handler_id="transition-handler",
        handler_version="handler/v1",
        graph_id="paper-analysis",
        graph_version="graph/v1",
        policy_id="harness-policy",
        policy_version="policy/v1",
        schema_id="io.newsroom.workflow-transition",
        schema_version="io.newsroom.workflow-transition/v2",
        expected_activity=activity if activity_required else None,
        recorded_activity_ref=record_ref if activity_required else None,
    )


def _verifier(
    commands: tuple[CanonicalDeterministicCommand, ...],
    *,
    recorded: tuple[CanonicalDeterministicCommand, ...] | None = None,
    activity_required: bool = False,
    activity: ReplayActivityRecord | None = None,
) -> tuple[HistoryVerifier, ReplayEvent]:
    handler = _handler_for(commands, require_activity=activity_required)
    verifier = HistoryVerifier(
        versions=_registry(handler),
        activity_resolver=(
            _activity_resolver(activity) if activity_required else None
        ),
    )
    return verifier, _event(
        recorded=commands if recorded is None else recorded,
        policy=_policy(activity_required=activity_required),
    )


def test_command_is_canonical_checksum_verified_and_detached() -> None:
    refs = ["input://accepted/1"]
    checksums = [_ref("input-1")]
    command = CanonicalDeterministicCommand(
        ordinal=0,
        kind="schedule_activity",
        target="summarizer",
        handler_version="handler/v1",
        graph_version="workflow/v1",
        policy_version="policy/v1",
        input_refs=tuple(refs),
        input_checksums=tuple(checksums),
        budget_ref=_ref("budget-1"),
        gate_ref=_ref("gate-1"),
        decision_ref=_ref("decision-1"),
        causation_id="event-cause",
    )
    refs[0] = "mutated"
    checksums[0] = _ref("mutated")

    assert command.input_refs == ("input://accepted/1",)
    assert command.command_checksum == checksum_for(command.checksum_projection())
    assert CanonicalDeterministicCommand.from_dict(command.to_dict()) == command

    corrupt = command.to_dict()
    corrupt["target"] = "different"
    with pytest.raises(ValueError, match="command checksum"):
        CanonicalDeterministicCommand.from_dict(corrupt)


def test_handler_input_is_integrity_bound_and_recorded_history_is_hidden() -> None:
    command = _command(0, target="from-handler-input")
    verifier = HistoryVerifier(versions=_registry(_input_driven_handler))
    event = _event(
        recorded=(command,),
        handler_input={"target": "from-handler-input"},
    )

    verified = verifier.start().verify_event(event)

    assert verified.state.next_command_ordinal == 1


def test_recorded_command_cannot_drive_expected_output() -> None:
    verifier = HistoryVerifier(versions=_registry(_input_driven_handler))
    event = _event(
        recorded=(_command(0, target="recorded-only"),),
        handler_input={"target": "expected-from-input"},
    )

    with pytest.raises(HistoryCommandMismatchError) as caught:
        verifier.start().verify_event(event)

    assert caught.value.reason_class == "command_nondeterminism"


def test_exact_version_registry_never_falls_back_to_latest() -> None:
    registry = ExactVersionRegistry()
    handler = _handler_for(())
    registry.register(
        ExactVersionRegistration("reducer", "handler", "v2", handler)
    )

    with pytest.raises(HistoryIncompatibleVersionError) as caught:
        registry.resolve("reducer", "handler", "v1", sequence=7)

    assert caught.value.sequence == 7
    assert caught.value.reason_class == "incompatible_version"
    assert caught.value.details["requested_version"] == "v1"


def test_explicit_version_migration_is_bounded_and_resolves_target() -> None:
    registry = ExactVersionRegistry()
    registry.register(
        ExactVersionRegistration("policy", "routing", "v2", "pinned")
    )
    registry.register_migration(
        component_kind="policy",
        component_id="routing",
        source_version="v1",
        target_version="v2",
        migrate=lambda value: {**value, "migrated": True},
    )

    resolved, value, migrations = registry.migrate_and_resolve(
        "policy", "routing", "v1", {"original": True}, sequence=3
    )

    assert resolved.version == "v2"
    assert value == {"original": True, "migrated": True}
    assert [(item.component, item.version) for item in migrations] == [
        ("migration:policy:routing:v1", "v2")
    ]


@pytest.mark.parametrize(
    ("recorded", "kind"),
    [
        ((), CommandMismatchKind.COUNT),
        ((_command(1),), CommandMismatchKind.ORDER),
        ((_command(0, kind="emit_decision"),), CommandMismatchKind.TYPE),
        (
            (_command(0, handler_version="handler/v2"),),
            CommandMismatchKind.VERSION,
        ),
        (
            (_command(0, decision_ref=_ref("different-decision")),),
            CommandMismatchKind.CONTENT,
        ),
    ],
)
def test_recorded_comparator_types_first_mismatch(
    recorded: tuple[CanonicalDeterministicCommand, ...],
    kind: CommandMismatchKind,
) -> None:
    comparison = RecordedCommandComparator().compare((_command(0),), recorded)

    assert not comparison.matches
    assert comparison.mismatch_kind is kind
    assert comparison.command_index == 0


def test_history_session_verifies_event_and_returns_canonical_checkpoint() -> None:
    command = _command(0)
    verifier, event = _verifier((command,))

    original = verifier.start()
    advanced = original.verify_event(event)

    assert original.state.next_sequence == 1
    assert advanced.state.next_sequence == 2
    assert advanced.state.next_command_ordinal == 1
    assert [(item.component, item.version) for item in advanced.pinned_versions] == [
        ("graph:paper-analysis", "graph/v1"),
        ("policy:harness-policy", "policy/v1"),
        ("reducer:transition-handler", "handler/v1"),
        (
            "schema:io.newsroom.workflow-transition",
            "io.newsroom.workflow-transition/v2",
        ),
    ]
    checkpoint = advanced.checkpoint()
    assert checkpoint["next_sequence"] == 2
    assert checkpoint["next_command_ordinal"] == 1
    assert "payload" not in checkpoint
    assert "activity_result" not in checkpoint
    assert HistoryVerificationState.from_checkpoint(checkpoint) == advanced.state


def test_sessions_are_independent_and_can_resume_concurrently() -> None:
    verifier, event = _verifier((_command(0),))
    first = verifier.start().verify_event(event)
    resumed_a = verifier.start(first.checkpoint())
    resumed_b = verifier.start(first.checkpoint())

    assert resumed_a is not resumed_b
    assert resumed_a.state == resumed_b.state == first.state
    assert verifier.start().state.next_sequence == 1
    with pytest.raises(FrozenInstanceError):
        first._state = verifier.start().state


def test_history_verifier_reports_first_command_mismatch_and_stops() -> None:
    verifier, event = _verifier(
        (_command(0), _command(1, target="publisher")),
        recorded=(
            _command(0),
            _command(1, target="different"),
            _command(2, target="unreachable"),
        ),
    )

    with pytest.raises(HistoryCommandMismatchError) as caught:
        verifier.start().verify_event(event)

    assert caught.value.sequence == 1
    assert caught.value.details["command_index"] == 1
    assert caught.value.details["mismatch_kind"] == "type"


def test_missing_activity_result_fails_before_handler_and_without_fallback() -> None:
    verifier, event = _verifier(
        (_command(0),),
        activity_required=True,
        activity=None,
    )

    with pytest.raises(HistoryMissingActivityError) as caught:
        verifier.start().verify_event(event)

    assert caught.value.reason_class == "missing_activity_result"


def test_recorded_activity_is_passed_to_handler_without_live_capability() -> None:
    _activity, record, _record_ref = _activity_material()
    verifier, event = _verifier(
        (_command(0),),
        activity_required=True,
        activity=record,
    )

    session = verifier.start().verify_event(event)

    assert (
        "activity_handler:llm:newsroom.activity/v1",
        "activity/v1",
    ) in {
        (item.component, item.version) for item in session.pinned_versions
    }


def test_incompatible_component_version_fails_before_handler() -> None:
    handler = _handler_for((_command(0),))
    verifier = HistoryVerifier(
        versions=_registry(handler),
    )
    event = _event(
        policy=replace(_policy(), graph_version="workflow/missing"),
    )

    with pytest.raises(HistoryIncompatibleVersionError) as caught:
        verifier.start().verify_event(event)

    assert caught.value.details["component"] == "graph:paper-analysis"


def test_noncontiguous_event_and_corrupt_recorded_order_fail_closed() -> None:
    verifier, event = _verifier((_command(0),), recorded=(_command(2),))

    with pytest.raises(HistoryCorruptionError, match="sequence is not contiguous"):
        verifier.start().verify_event(replace(event, stream_sequence=2))
    with pytest.raises(HistoryCorruptionError) as caught:
        verifier.start().verify_event(event)
    assert caught.value.reason_class == "corrupt_history"
    assert caught.value.details["actual_ordinal"] == 2


def test_history_registration_rejects_live_provider_capability_without_calling_it() -> None:
    class LiveProvider:
        def __init__(self) -> None:
            self.calls = 0

        def call(self) -> None:
            self.calls += 1

    provider = LiveProvider()

    def unsafe_handler(
        _event: ReplayEvent,
        _handler_input: Mapping[str, Any],
        _activity_result: ResolvedReplayActivity | None,
    ) -> tuple[CanonicalDeterministicCommand, ...]:
        provider.call()
        return ()

    with pytest.raises(ValueError, match="forbidden dependency"):
        ExactVersionRegistration(
            "reducer",
            "unsafe-handler",
            "v1",
            unsafe_handler,
        )

    assert provider.calls == 0


def test_history_registration_allows_audited_comprehensions() -> None:
    def comprehension_handler(
        _event: ReplayEvent,
        handler_input: Mapping[str, Any],
        _activity_result: ResolvedReplayActivity | None,
    ) -> tuple[CanonicalDeterministicCommand, ...]:
        values = [str(item) for item in handler_input.get("values", ())]
        return tuple(_command(index) for index, _item in enumerate(values))

    registration = ExactVersionRegistration(
        "reducer",
        "comprehension-handler",
        "v1",
        comprehension_handler,
    )

    assert registration.handler is comprehension_handler


def test_history_registration_rejects_forbidden_builtin_inside_comprehension() -> None:
    def unsafe_comprehension_handler(
        _event: ReplayEvent,
        handler_input: Mapping[str, Any],
        _activity_result: ResolvedReplayActivity | None,
    ) -> tuple[CanonicalDeterministicCommand, ...]:
        return tuple(open(str(item)) for item in handler_input.get("values", ()))  # type: ignore[arg-type,return-value]

    with pytest.raises(ValueError, match="forbidden builtin: open"):
        ExactVersionRegistration(
            "reducer",
            "unsafe-comprehension-handler",
            "v1",
            unsafe_comprehension_handler,
        )


def test_history_registration_rejects_module_used_only_inside_comprehension() -> None:
    def unsafe_comprehension_handler(
        _event: ReplayEvent,
        handler_input: Mapping[str, Any],
        _activity_result: ResolvedReplayActivity | None,
    ) -> tuple[CanonicalDeterministicCommand, ...]:
        return tuple(os.getcwd() for _item in handler_input.get("values", ()))  # type: ignore[return-value]

    with pytest.raises(ValueError, match="forbidden dependency os: module"):
        ExactVersionRegistration(
            "reducer",
            "module-comprehension-handler",
            "v1",
            unsafe_comprehension_handler,
        )


def test_history_registration_still_rejects_explicit_nested_functions() -> None:
    def nested_function_handler(
        _event: ReplayEvent,
        _handler_input: Mapping[str, Any],
        _activity_result: ResolvedReplayActivity | None,
    ) -> tuple[CanonicalDeterministicCommand, ...]:
        return ((lambda: _command(0))(),)

    with pytest.raises(ValueError, match="forbidden operation: MAKE_FUNCTION"):
        ExactVersionRegistration(
            "reducer",
            "nested-function-handler",
            "v1",
            nested_function_handler,
        )


def test_history_verifier_applies_registered_version_migration_end_to_end() -> None:
    command = _command(0)
    handler = _handler_for((command,))
    versions = _registry(handler)

    def migrate_policy(value):
        return {
            **value,
            "policy": {
                **value["policy"],
                "policy_version": "policy/v1",
            },
        }

    versions.register_migration(
        component_kind="policy",
        component_id="harness-policy",
        source_version="policy/v0",
        target_version="policy/v1",
        migrate=migrate_policy,
    )
    verifier = HistoryVerifier(versions=versions)
    event = _event(
        recorded=(command,),
        policy=replace(_policy(), policy_version="policy/v0"),
    )

    session = verifier.start().verify_event(event)

    assert (
        "migration:policy:harness-policy:policy/v0",
        "policy/v1",
    ) in {
        (item.component, item.version) for item in session.pinned_versions
    }


def test_history_module_has_no_live_runtime_capability_imports() -> None:
    target = ROOT / "framework" / "events" / "runtime" / "history.py"
    source = target.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(target))
    imports = {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module is not None
    }
    imports.update(
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    )
    forbidden = (
        "backend",
        "infrastructure",
        "interfaces",
        "framework.events.bus",
        "framework.events.runtime.publisher",
        "framework.events.runtime.delivery",
        "framework.tool",
        "framework.memory",
        "framework.llm",
    )

    assert not {
        module
        for module in imports
        if any(module == root or module.startswith(f"{root}.") for root in forbidden)
    }
    assert "EventBus" not in source
    assert "publish(" not in source
