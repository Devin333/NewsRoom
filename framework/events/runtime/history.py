from __future__ import annotations

import dis
import inspect
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field, fields, is_dataclass, replace
from enum import Enum
from types import CodeType, FunctionType, ModuleType
from typing import TYPE_CHECKING, Any, TypeAlias

from framework.events.canonical import (
    CanonicalValue,
    PayloadReference,
    checksum_for,
    normalize_canonical_json,
)
from framework.events.runtime.activities import (
    ReplayActivityCorruptionError,
    ReplayActivityDescriptor,
    ReplayActivityIncompleteError,
    ReplayActivityMissingError,
    ReplayActivityResolutionError,
    ReplayActivityResolverPort,
    ReplayActivityVersionError,
    ResolvedReplayActivity,
)
from framework.events.runtime.models import ReplayVersion

if TYPE_CHECKING:
    from framework.events.runtime.replay_engine import ReplayEvent


_VERSION_COMPONENT_KINDS = frozenset(
    {"workflow", "reducer", "policy", "schema", "activity_handler"}
)
DETERMINISTIC_HISTORY_RECORD_SCHEMA = "newsroom.deterministic-history/v1"
DETERMINISTIC_HISTORY_EXTENSION = "deterministic_history"
_PURE_HISTORY_ALLOWED_BUILTINS = frozenset(
    {
        "all",
        "any",
        "bool",
        "dict",
        "enumerate",
        "float",
        "int",
        "isinstance",
        "len",
        "list",
        "max",
        "min",
        "next",
        "range",
        "reversed",
        "set",
        "sorted",
        "str",
        "sum",
        "tuple",
        "TypeError",
        "ValueError",
        "zip",
    }
)
_PURE_HISTORY_FORBIDDEN_OPCODES = frozenset(
    {
        "DELETE_DEREF",
        "DELETE_GLOBAL",
        "IMPORT_FROM",
        "IMPORT_NAME",
        "IMPORT_STAR",
        "LOAD_BUILD_CLASS",
        "MAKE_FUNCTION",
        "STORE_DEREF",
        "STORE_GLOBAL",
    }
)
_PURE_HISTORY_FORBIDDEN_NAMES = frozenset(
    {
        "__builtins__",
        "__class__",
        "__code__",
        "__dict__",
        "__func__",
        "__globals__",
        "__import__",
        "__mro__",
        "__subclasses__",
    }
)
_PURE_HISTORY_TRUSTED_FUNCTIONS = frozenset(
    {checksum_for, normalize_canonical_json}
)


class HistoryVerificationError(RuntimeError):
    """Base class for fail-closed deterministic history verification."""

    reason_class = "history_verification_failed"

    def __init__(
        self,
        *,
        sequence: int,
        reason: str,
        details: Mapping[str, CanonicalValue] | None = None,
    ) -> None:
        self.sequence = _positive_int(sequence, "sequence")
        self.reason = _required_text(reason, "reason")
        normalized = normalize_canonical_json(
            details or {}, path="$.history_error.details"
        )
        if not isinstance(normalized, Mapping):  # pragma: no cover - constructor input
            raise TypeError("history error details must be an object")
        self.details = normalized
        super().__init__(
            f"{self.reason_class} at stream sequence {self.sequence}: {self.reason}"
        )


class HistoryCommandMismatchError(HistoryVerificationError):
    reason_class = "command_nondeterminism"


class HistoryMissingActivityError(HistoryVerificationError):
    reason_class = "missing_activity_result"


class HistoryIncompatibleVersionError(HistoryVerificationError):
    reason_class = "incompatible_version"


class HistoryCorruptionError(HistoryVerificationError):
    reason_class = "corrupt_history"


class CommandMismatchKind(str, Enum):
    COUNT = "count"
    ORDER = "order"
    TYPE = "type"
    CONTENT = "content"
    VERSION = "version"


@dataclass(frozen=True, slots=True)
class DeterministicCommand:
    """Complete deterministic command material persisted for exact replay."""

    ordinal: int
    kind: str
    target: str
    handler_version: str
    workflow_version: str
    policy_version: str
    input_refs: tuple[str, ...]
    input_checksums: tuple[str, ...]
    budget_ref: str | None = None
    gate_ref: str | None = None
    decision_ref: str | None = None
    causation_id: str | None = None
    command_checksum: str = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "ordinal", _nonnegative_int(self.ordinal, "ordinal"))
        for field_name in (
            "kind",
            "target",
            "handler_version",
            "workflow_version",
            "policy_version",
        ):
            object.__setattr__(
                self,
                field_name,
                _required_text(getattr(self, field_name), field_name),
            )
        object.__setattr__(
            self,
            "input_refs",
            tuple(_required_text(value, "input_ref") for value in self.input_refs),
        )
        object.__setattr__(
            self,
            "input_checksums",
            tuple(_checksum(value, "input_checksum") for value in self.input_checksums),
        )
        if len(self.input_refs) != len(self.input_checksums):
            raise ValueError("input_refs and input_checksums must have equal lengths")
        if len(set(self.input_refs)) != len(self.input_refs):
            raise ValueError("input_refs must be unique within one command")
        for field_name in (
            "budget_ref",
            "gate_ref",
            "decision_ref",
            "causation_id",
        ):
            object.__setattr__(
                self,
                field_name,
                _optional_text(getattr(self, field_name), field_name),
            )
        for field_name in ("budget_ref", "gate_ref", "decision_ref"):
            value = getattr(self, field_name)
            if value is not None:
                _checksum(value, field_name)
        object.__setattr__(
            self,
            "command_checksum",
            checksum_for(self.checksum_projection()),
        )

    def checksum_projection(self) -> dict[str, CanonicalValue]:
        return {
            "ordinal": self.ordinal,
            "kind": self.kind,
            "target": self.target,
            "handler_version": self.handler_version,
            "workflow_version": self.workflow_version,
            "policy_version": self.policy_version,
            "input_refs": list(self.input_refs),
            "input_checksums": list(self.input_checksums),
            "budget_ref": self.budget_ref,
            "gate_ref": self.gate_ref,
            "decision_ref": self.decision_ref,
            "causation_id": self.causation_id,
        }

    def to_dict(self) -> dict[str, CanonicalValue]:
        return {**self.checksum_projection(), "command_checksum": self.command_checksum}

    def version_projection(self) -> tuple[str, str, str]:
        return (
            self.handler_version,
            self.workflow_version,
            self.policy_version,
        )

    def type_projection(self) -> tuple[str, str]:
        return (self.kind, self.target)

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> CanonicalDeterministicCommand:
        allowed = {
            "ordinal",
            "kind",
            "target",
            "handler_version",
            "workflow_version",
            "policy_version",
            "input_refs",
            "input_checksums",
            "budget_ref",
            "gate_ref",
            "decision_ref",
            "causation_id",
            "command_checksum",
        }
        unknown = set(value) - allowed
        if unknown:
            raise ValueError(
                "unknown deterministic command field(s): " + ", ".join(sorted(unknown))
            )
        command = cls(
            ordinal=value.get("ordinal"),
            kind=value.get("kind"),
            target=value.get("target"),
            handler_version=value.get("handler_version"),
            workflow_version=value.get("workflow_version"),
            policy_version=value.get("policy_version"),
            input_refs=_string_tuple(value.get("input_refs"), "input_refs"),
            input_checksums=_string_tuple(
                value.get("input_checksums"), "input_checksums"
            ),
            budget_ref=value.get("budget_ref"),
            gate_ref=value.get("gate_ref"),
            decision_ref=value.get("decision_ref"),
            causation_id=value.get("causation_id"),
        )
        supplied = _checksum(value.get("command_checksum"), "command_checksum")
        if supplied != command.command_checksum:
            raise ValueError("deterministic command checksum does not match")
        return command


CanonicalDeterministicCommand = DeterministicCommand


VersionMigration = Callable[[Any], Any]


@dataclass(frozen=True, slots=True)
class ExactVersionRegistration:
    component_kind: str
    component_id: str
    version: str
    handler: Any

    def __post_init__(self) -> None:
        kind = _required_text(self.component_kind, "component_kind")
        if kind not in _VERSION_COMPONENT_KINDS:
            raise ValueError(f"unsupported replay version component kind: {kind}")
        object.__setattr__(self, "component_kind", kind)
        object.__setattr__(
            self, "component_id", _required_text(self.component_id, "component_id")
        )
        object.__setattr__(self, "version", _required_text(self.version, "version"))
        if self.handler is None:
            raise ValueError("version handler is required")
        if kind == "reducer":
            _audit_history_function(
                self.handler,
                field_name="deterministic history handler",
                parameter_count=3,
            )

    @property
    def component(self) -> str:
        return f"{self.component_kind}:{self.component_id}"

    @property
    def replay_version(self) -> ReplayVersion:
        return ReplayVersion(component=self.component, version=self.version)


@dataclass(frozen=True, slots=True)
class _VersionMigrationRegistration:
    component_kind: str
    component_id: str
    source_version: str
    target_version: str
    migrate: VersionMigration


class ExactVersionRegistry:
    """Exact-only version registry; migrations are explicit and never latest fallback."""

    def __init__(self) -> None:
        self._registrations: dict[tuple[str, str, str], ExactVersionRegistration] = {}
        self._migrations: dict[
            tuple[str, str, str], _VersionMigrationRegistration
        ] = {}

    def register(self, registration: ExactVersionRegistration) -> None:
        if not isinstance(registration, ExactVersionRegistration):
            raise TypeError("registration must be ExactVersionRegistration")
        key = (
            registration.component_kind,
            registration.component_id,
            registration.version,
        )
        if key in self._registrations:
            raise ValueError(f"duplicate replay version registration: {registration.component}")
        self._registrations[key] = registration

    def register_migration(
        self,
        *,
        component_kind: str,
        component_id: str,
        source_version: str,
        target_version: str,
        migrate: VersionMigration,
    ) -> None:
        kind = _required_text(component_kind, "component_kind")
        if kind not in _VERSION_COMPONENT_KINDS:
            raise ValueError(f"unsupported replay version component kind: {kind}")
        component = _required_text(component_id, "component_id")
        source = _required_text(source_version, "source_version")
        target = _required_text(target_version, "target_version")
        if source == target:
            raise ValueError("version migration must change the version")
        if not callable(migrate):
            raise TypeError("version migration must be callable")
        _audit_history_function(
            migrate,
            field_name="replay version migration",
            parameter_count=1,
        )
        key = (kind, component, source)
        if key in self._migrations:
            raise ValueError("duplicate replay version migration source")
        self._migrations[key] = _VersionMigrationRegistration(
            component_kind=kind,
            component_id=component,
            source_version=source,
            target_version=target,
            migrate=migrate,
        )

    def resolve(
        self,
        component_kind: str,
        component_id: str,
        version: str,
        *,
        sequence: int,
    ) -> ExactVersionRegistration:
        kind = _required_text(component_kind, "component_kind")
        component = _required_text(component_id, "component_id")
        requested = _required_text(version, "version")
        registration = self._registrations.get((kind, component, requested))
        if registration is None:
            raise HistoryIncompatibleVersionError(
                sequence=sequence,
                reason="exact replay component version is unavailable",
                details={
                    "component": f"{kind}:{component}",
                    "requested_version": requested,
                },
            )
        return registration

    def migrate_and_resolve(
        self,
        component_kind: str,
        component_id: str,
        version: str,
        value: Any,
        *,
        sequence: int,
    ) -> tuple[ExactVersionRegistration, Any, tuple[ReplayVersion, ...]]:
        kind = _required_text(component_kind, "component_kind")
        component = _required_text(component_id, "component_id")
        current = _required_text(version, "version")
        applied: list[ReplayVersion] = []
        visited: set[str] = set()
        migrated = value
        while True:
            registration = self._registrations.get((kind, component, current))
            if registration is not None:
                return registration, migrated, tuple(applied)
            if current in visited:
                raise HistoryIncompatibleVersionError(
                    sequence=sequence,
                    reason="replay component version migration contains a cycle",
                    details={"component": f"{kind}:{component}", "version": current},
                )
            visited.add(current)
            migration = self._migrations.get((kind, component, current))
            if migration is None:
                raise HistoryIncompatibleVersionError(
                    sequence=sequence,
                    reason="exact replay component version is unavailable",
                    details={
                        "component": f"{kind}:{component}",
                        "requested_version": version,
                    },
                )
            try:
                migrated = migration.migrate(migrated)
            except Exception as exc:
                raise HistoryIncompatibleVersionError(
                    sequence=sequence,
                    reason="replay component version migration failed",
                    details={
                        "component": f"{kind}:{component}",
                        "source_version": current,
                        "target_version": migration.target_version,
                    },
                ) from exc
            applied.append(
                ReplayVersion(
                    component=f"migration:{kind}:{component}:{current}",
                    version=migration.target_version,
                )
            )
            current = migration.target_version


@dataclass(frozen=True, slots=True)
class CommandComparison:
    mismatch_kind: CommandMismatchKind | None
    command_index: int | None = None
    expected: CanonicalDeterministicCommand | None = None
    recorded: CanonicalDeterministicCommand | None = None

    @property
    def matches(self) -> bool:
        return self.mismatch_kind is None


class RecordedCommandComparator:
    def compare(
        self,
        expected: Iterable[CanonicalDeterministicCommand],
        recorded: Iterable[CanonicalDeterministicCommand],
    ) -> CommandComparison:
        expected_values = _commands(expected, "expected")
        recorded_values = _commands(recorded, "recorded")
        limit = min(len(expected_values), len(recorded_values))
        for index in range(limit):
            wanted = expected_values[index]
            actual = recorded_values[index]
            if wanted.ordinal != actual.ordinal:
                return CommandComparison(
                    CommandMismatchKind.ORDER, index, wanted, actual
                )
            if wanted.type_projection() != actual.type_projection():
                return CommandComparison(CommandMismatchKind.TYPE, index, wanted, actual)
            if wanted.version_projection() != actual.version_projection():
                return CommandComparison(
                    CommandMismatchKind.VERSION, index, wanted, actual
                )
            if wanted.command_checksum != actual.command_checksum:
                return CommandComparison(
                    CommandMismatchKind.CONTENT, index, wanted, actual
                )
        if len(expected_values) != len(recorded_values):
            return CommandComparison(
                CommandMismatchKind.COUNT,
                limit,
                expected_values[limit] if limit < len(expected_values) else None,
                recorded_values[limit] if limit < len(recorded_values) else None,
            )
        return CommandComparison(None)


DeterministicHistoryHandler: TypeAlias = Callable[
    [Any, Mapping[str, CanonicalValue], ResolvedReplayActivity | None],
    Iterable[CanonicalDeterministicCommand],
]


@dataclass(frozen=True, slots=True)
class HistoryEventPolicy:
    handler_id: str
    handler_version: str
    workflow_id: str
    workflow_version: str
    policy_id: str
    policy_version: str
    schema_id: str
    schema_version: str
    expected_activity: ReplayActivityDescriptor | None = None
    recorded_activity_ref: PayloadReference | None = None

    def __post_init__(self) -> None:
        for field_name in (
            "handler_id",
            "handler_version",
            "workflow_id",
            "workflow_version",
            "policy_id",
            "policy_version",
            "schema_id",
            "schema_version",
        ):
            object.__setattr__(
                self,
                field_name,
                _required_text(getattr(self, field_name), field_name),
            )
        if self.expected_activity is not None and not isinstance(
            self.expected_activity, ReplayActivityDescriptor
        ):
            raise TypeError("expected_activity must be ReplayActivityDescriptor")
        if self.recorded_activity_ref is not None and not isinstance(
            self.recorded_activity_ref, PayloadReference
        ):
            raise TypeError("recorded_activity_ref must be PayloadReference")
        if (self.expected_activity is None) != (self.recorded_activity_ref is None):
            raise ValueError(
                "expected_activity and recorded_activity_ref must be supplied together"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "handler_id": self.handler_id,
            "handler_version": self.handler_version,
            "workflow_id": self.workflow_id,
            "workflow_version": self.workflow_version,
            "policy_id": self.policy_id,
            "policy_version": self.policy_version,
            "schema_id": self.schema_id,
            "schema_version": self.schema_version,
            "expected_activity": (
                None
                if self.expected_activity is None
                else self.expected_activity.to_dict()
            ),
            "recorded_activity_ref": (
                None
                if self.recorded_activity_ref is None
                else self.recorded_activity_ref.to_dict()
            ),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> HistoryEventPolicy:
        allowed = {
            "handler_id",
            "handler_version",
            "workflow_id",
            "workflow_version",
            "policy_id",
            "policy_version",
            "schema_id",
            "schema_version",
            "expected_activity",
            "recorded_activity_ref",
        }
        unknown = set(value) - allowed
        if unknown:
            raise ValueError(
                "unknown history policy field(s): " + ", ".join(sorted(unknown))
            )
        activity = value.get("expected_activity")
        recorded_ref = value.get("recorded_activity_ref")
        return cls(
            handler_id=value.get("handler_id"),
            handler_version=value.get("handler_version"),
            workflow_id=value.get("workflow_id"),
            workflow_version=value.get("workflow_version"),
            policy_id=value.get("policy_id"),
            policy_version=value.get("policy_version"),
            schema_id=value.get("schema_id"),
            schema_version=value.get("schema_version"),
            expected_activity=(
                None
                if activity is None
                else ReplayActivityDescriptor.from_dict(
                    _mapping(activity, "expected_activity")
                )
            ),
            recorded_activity_ref=(
                None
                if recorded_ref is None
                else PayloadReference.from_dict(
                    _mapping(recorded_ref, "recorded_activity_ref")
                )
            ),
        )


@dataclass(frozen=True, slots=True)
class DeterministicHistoryRecord:
    """Integrity-bound handler input, policy, and commands for one event."""

    policy: HistoryEventPolicy
    commands: tuple[CanonicalDeterministicCommand, ...]
    handler_input: Mapping[str, CanonicalValue] = field(default_factory=dict)
    schema: str = DETERMINISTIC_HISTORY_RECORD_SCHEMA
    record_checksum: str = field(init=False)

    def __post_init__(self) -> None:
        if not isinstance(self.policy, HistoryEventPolicy):
            raise TypeError("policy must be HistoryEventPolicy")
        commands = _commands(self.commands, "recorded")
        schema = _required_text(self.schema, "schema")
        if schema != DETERMINISTIC_HISTORY_RECORD_SCHEMA:
            raise ValueError("unsupported deterministic history record schema")
        handler_input = normalize_canonical_json(
            self.handler_input,
            path="$.deterministic_history.handler_input",
        )
        if not isinstance(handler_input, Mapping):
            raise TypeError("deterministic history handler_input must be an object")
        object.__setattr__(self, "commands", commands)
        object.__setattr__(self, "handler_input", handler_input)
        object.__setattr__(self, "schema", schema)
        object.__setattr__(
            self,
            "record_checksum",
            checksum_for(self.checksum_projection()),
        )

    def checksum_projection(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "policy": self.policy.to_dict(),
            "handler_input": self.handler_input,
            "commands": [command.to_dict() for command in self.commands],
        }

    def to_dict(self) -> dict[str, Any]:
        return {**self.checksum_projection(), "record_checksum": self.record_checksum}

    def verify_integrity(self) -> None:
        if checksum_for(self.checksum_projection()) != self.record_checksum:
            raise ValueError("deterministic history record checksum does not match")

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> DeterministicHistoryRecord:
        allowed = {
            "schema",
            "policy",
            "handler_input",
            "commands",
            "record_checksum",
        }
        unknown = set(value) - allowed
        if unknown:
            raise ValueError(
                "unknown deterministic history field(s): "
                + ", ".join(sorted(unknown))
            )
        commands = value.get("commands")
        if not isinstance(commands, list | tuple):
            raise TypeError("deterministic history commands must be an array")
        record = cls(
            schema=value.get("schema"),
            policy=HistoryEventPolicy.from_dict(
                _mapping(value.get("policy"), "policy")
            ),
            handler_input=_mapping(
                value.get("handler_input", {}),
                "handler_input",
            ),
            commands=tuple(
                DeterministicCommand.from_dict(_mapping(item, "command"))
                for item in commands
            ),
        )
        if _checksum(value.get("record_checksum"), "record_checksum") != (
            record.record_checksum
        ):
            raise ValueError("deterministic history record checksum does not match")
        return record


@dataclass(frozen=True, slots=True)
class HistoryVerificationState:
    next_sequence: int
    next_command_ordinal: int
    history_checksum: str
    pinned_versions: tuple[ReplayVersion, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "next_sequence",
            _positive_int(self.next_sequence, "next_sequence"),
        )
        object.__setattr__(
            self,
            "next_command_ordinal",
            _nonnegative_int(self.next_command_ordinal, "next_command_ordinal"),
        )
        object.__setattr__(
            self,
            "history_checksum",
            _checksum(self.history_checksum, "history_checksum"),
        )
        object.__setattr__(
            self,
            "pinned_versions",
            _merge_pinned_versions((), self.pinned_versions, sequence=self.next_sequence),
        )

    def to_checkpoint(self) -> Mapping[str, CanonicalValue]:
        return normalize_canonical_json(
            {
                "next_sequence": self.next_sequence,
                "next_command_ordinal": self.next_command_ordinal,
                "history_checksum": self.history_checksum,
                "pinned_versions": [
                    {"component": item.component, "version": item.version}
                    for item in self.pinned_versions
                ],
            },
            path="$.history_checkpoint",
        )  # type: ignore[return-value]

    @classmethod
    def from_checkpoint(
        cls, value: Mapping[str, Any]
    ) -> HistoryVerificationState:
        allowed = {
            "next_sequence",
            "next_command_ordinal",
            "history_checksum",
            "pinned_versions",
        }
        unknown = set(value) - allowed
        if unknown:
            raise ValueError(
                "unknown history checkpoint field(s): " + ", ".join(sorted(unknown))
            )
        versions = value.get("pinned_versions")
        if not isinstance(versions, list | tuple):
            raise TypeError("history checkpoint pinned_versions must be an array")
        return cls(
            next_sequence=value.get("next_sequence"),
            next_command_ordinal=value.get("next_command_ordinal"),
            history_checksum=value.get("history_checksum"),
            pinned_versions=tuple(
                ReplayVersion(
                    component=_mapping(item, "pinned version").get("component"),
                    version=_mapping(item, "pinned version").get("version"),
                )
                for item in versions
            ),
        )


@dataclass(frozen=True, slots=True)
class HistoryEventVerification:
    state: HistoryVerificationState
    expected_commands: tuple[CanonicalDeterministicCommand, ...]
    recorded_commands: tuple[CanonicalDeterministicCommand, ...]


@dataclass(frozen=True, slots=True)
class HistoryVerificationSession:
    """Single-replay immutable verification cursor."""

    _verifier: HistoryVerifier = field(repr=False, compare=False)
    _state: HistoryVerificationState

    @property
    def state(self) -> HistoryVerificationState:
        return self._state

    @property
    def pinned_versions(self) -> tuple[ReplayVersion, ...]:
        return self._state.pinned_versions

    def checkpoint(self) -> Mapping[str, CanonicalValue]:
        return self._state.to_checkpoint()

    def verify_event(self, event: ReplayEvent) -> HistoryVerificationSession:
        result = self._verifier.verify_event(self._state, event)
        return HistoryVerificationSession(self._verifier, result.state)


class HistoryVerifier:
    """Generates expected commands from pinned pure handlers and compares history."""

    def __init__(
        self,
        *,
        versions: ExactVersionRegistry,
        activity_resolver: ReplayActivityResolverPort | None = None,
        comparator: RecordedCommandComparator | None = None,
    ) -> None:
        if not isinstance(versions, ExactVersionRegistry):
            raise TypeError("versions must be ExactVersionRegistry")
        if activity_resolver is not None and not isinstance(
            activity_resolver,
            ReplayActivityResolverPort,
        ):
            raise TypeError("activity_resolver must implement ReplayActivityResolverPort")
        self._versions = versions
        self._activity_resolver = activity_resolver
        self._comparator = comparator or RecordedCommandComparator()

    def start(
        self,
        checkpoint: Mapping[str, Any] | HistoryVerificationState | None = None,
        *,
        first_sequence: int = 1,
    ) -> HistoryVerificationSession:
        if checkpoint is None:
            state = HistoryVerificationState(
                next_sequence=_positive_int(first_sequence, "first_sequence"),
                next_command_ordinal=0,
                history_checksum=checksum_for(
                    {
                        "history_verifier": "newsroom.replay-history/v1",
                        "first_sequence": first_sequence,
                    }
                ),
            )
        elif isinstance(checkpoint, HistoryVerificationState):
            state = checkpoint
        elif isinstance(checkpoint, Mapping):
            state = HistoryVerificationState.from_checkpoint(checkpoint)
        else:
            raise TypeError("history checkpoint must be a mapping or state")
        return HistoryVerificationSession(self, state)

    def verify_event(
        self,
        state: HistoryVerificationState,
        event: ReplayEvent,
    ) -> HistoryEventVerification:
        if not isinstance(state, HistoryVerificationState):
            raise TypeError("state must be HistoryVerificationState")
        _validate_replay_event(event)
        if event.stream_sequence != state.next_sequence:
            raise HistoryCorruptionError(
                sequence=event.stream_sequence,
                reason="history verification sequence is not contiguous",
                details={
                    "expected_sequence": state.next_sequence,
                    "actual_sequence": event.stream_sequence,
                },
            )
        history_value = getattr(event, "history", None)
        if not isinstance(history_value, Mapping):
            raise HistoryCorruptionError(
                sequence=event.stream_sequence,
                reason="event is missing its deterministic history record",
            )
        try:
            history = DeterministicHistoryRecord.from_dict(history_value)
            history.verify_integrity()
        except Exception as exc:
            raise HistoryCorruptionError(
                sequence=event.stream_sequence,
                reason="deterministic history record is corrupt",
            ) from exc
        history, registrations, version_migrations = self._resolve_history_versions(
            history,
            sequence=event.stream_sequence,
        )
        policy = history.policy
        activity_result: ResolvedReplayActivity | None = None
        activity_version: ReplayVersion | None = None
        if policy.expected_activity is not None:
            if self._activity_resolver is None:
                raise HistoryMissingActivityError(
                    sequence=event.stream_sequence,
                    reason="recorded activity resolver is unavailable",
                    details={
                        "activity_id": policy.expected_activity.activity_id,
                        "activity_kind": policy.expected_activity.activity_kind.value,
                    },
                )
            try:
                activity_result = self._activity_resolver.resolve(
                    policy.expected_activity,
                    policy.recorded_activity_ref,
                )
            except ReplayActivityVersionError as exc:
                raise HistoryIncompatibleVersionError(
                    sequence=event.stream_sequence,
                    reason="recorded activity handler version is incompatible",
                    details={
                        "activity_id": policy.expected_activity.activity_id,
                        "activity_kind": policy.expected_activity.activity_kind.value,
                        "contract_version": policy.expected_activity.contract_version,
                        "handler_version": policy.expected_activity.handler_version,
                    },
                ) from exc
            except (
                ReplayActivityMissingError,
                ReplayActivityIncompleteError,
            ) as exc:
                raise HistoryMissingActivityError(
                    sequence=event.stream_sequence,
                    reason="required recorded activity result is unavailable",
                    details={
                        "activity_id": policy.expected_activity.activity_id,
                        "activity_kind": policy.expected_activity.activity_kind.value,
                    },
                ) from exc
            except ReplayActivityCorruptionError as exc:
                raise HistoryCorruptionError(
                    sequence=event.stream_sequence,
                    reason="recorded activity history is corrupt",
                    details={"activity_id": policy.expected_activity.activity_id},
                ) from exc
            except ReplayActivityResolutionError as exc:
                raise HistoryCorruptionError(
                    sequence=event.stream_sequence,
                    reason="recorded activity history conflicts with the command",
                    details={"activity_id": policy.expected_activity.activity_id},
                ) from exc
            activity_version = ReplayVersion(
                component=(
                    "activity_handler:"
                    f"{activity_result.pinned_version.activity_kind.value}:"
                    f"{activity_result.pinned_version.contract_version}"
                ),
                version=activity_result.pinned_version.handler_version,
            )

        handler = registrations[-1].handler
        try:
            handler_event = replace(event, history=None)
            expected = _commands(
                handler(handler_event, history.handler_input, activity_result),
                "expected",
            )
            recorded = history.commands
        except HistoryVerificationError:
            raise
        except Exception as exc:
            raise HistoryCommandMismatchError(
                sequence=event.stream_sequence,
                reason="deterministic history handler failed",
            ) from exc
        _validate_command_ordinals(
            expected,
            state.next_command_ordinal,
            event.stream_sequence,
            source="expected",
        )
        _validate_command_ordinals(
            recorded,
            state.next_command_ordinal,
            event.stream_sequence,
            source="recorded",
        )
        comparison = self._comparator.compare(expected, recorded)
        if not comparison.matches:
            details: dict[str, CanonicalValue] = {
                "mismatch_kind": comparison.mismatch_kind.value,
                "command_index": comparison.command_index,
                "expected_count": len(expected),
                "recorded_count": len(recorded),
            }
            if comparison.expected is not None:
                details["expected_command_checksum"] = (
                    comparison.expected.command_checksum
                )
            if comparison.recorded is not None:
                details["recorded_command_checksum"] = (
                    comparison.recorded.command_checksum
                )
            raise HistoryCommandMismatchError(
                sequence=event.stream_sequence,
                reason="recorded deterministic commands do not match replay output",
                details=details,
            )

        pinned = tuple(item.replay_version for item in registrations)
        pinned += version_migrations
        if activity_version is not None:
            pinned += (activity_version,)
        next_state = HistoryVerificationState(
            next_sequence=event.stream_sequence + 1,
            next_command_ordinal=state.next_command_ordinal + len(expected),
            history_checksum=checksum_for(
                {
                    "previous": state.history_checksum,
                    "event_id": event.event_id,
                    "record_checksum": event.record_checksum,
                    "command_checksums": [item.command_checksum for item in recorded],
                }
            ),
            pinned_versions=_merge_pinned_versions(
                state.pinned_versions,
                pinned,
                sequence=event.stream_sequence,
            ),
        )
        return HistoryEventVerification(
            state=next_state,
            expected_commands=expected,
            recorded_commands=recorded,
        )

    def _resolve_history_versions(
        self,
        history: DeterministicHistoryRecord,
        *,
        sequence: int,
    ) -> tuple[
        DeterministicHistoryRecord,
        tuple[ExactVersionRegistration, ...],
        tuple[ReplayVersion, ...],
    ]:
        resolved: list[ExactVersionRegistration] = []
        migrations: list[ReplayVersion] = []
        current = history
        resolved_keys: set[tuple[str, str, str]] = set()
        for component_kind in ("workflow", "policy", "schema", "reducer"):
            component_id, version = _history_component(current.policy, component_kind)
            key = (component_kind, component_id, version)
            if key in resolved_keys:
                continue
            registration, migrated, applied = self._versions.migrate_and_resolve(
                component_kind,
                component_id,
                version,
                current.to_dict(),
                sequence=sequence,
            )
            if applied:
                try:
                    current = _history_record_from_migration(migrated)
                except Exception as exc:
                    raise HistoryIncompatibleVersionError(
                        sequence=sequence,
                        reason="replay history version migration returned invalid data",
                        details={
                            "component": f"{component_kind}:{component_id}",
                            "source_version": version,
                            "target_version": registration.version,
                        },
                    ) from exc
                migrated_id, migrated_version = _history_component(
                    current.policy,
                    component_kind,
                )
                if (
                    migrated_id != registration.component_id
                    or migrated_version != registration.version
                ):
                    raise HistoryIncompatibleVersionError(
                        sequence=sequence,
                        reason="replay history migration did not bind its target version",
                        details={
                            "component": f"{component_kind}:{component_id}",
                            "target_version": registration.version,
                        },
                    )
            resolved.append(registration)
            resolved_keys.add(
                (
                    component_kind,
                    registration.component_id,
                    registration.version,
                )
            )
            migrations.extend(applied)
        return current, tuple(resolved), tuple(migrations)


def _merge_pinned_versions(
    existing: Iterable[ReplayVersion],
    additions: Iterable[ReplayVersion],
    *,
    sequence: int,
) -> tuple[ReplayVersion, ...]:
    merged: dict[str, ReplayVersion] = {}
    for value in (*tuple(existing), *tuple(additions)):
        if not isinstance(value, ReplayVersion):
            raise TypeError("pinned versions must be ReplayVersion values")
        prior = merged.get(value.component)
        if prior is not None and prior.version != value.version:
            raise HistoryIncompatibleVersionError(
                sequence=sequence,
                reason="one replay history pins conflicting component versions",
                details={
                    "component": value.component,
                    "first_version": prior.version,
                    "second_version": value.version,
                },
            )
        merged[value.component] = value
    return tuple(merged[key] for key in sorted(merged))


def _history_component(
    policy: HistoryEventPolicy,
    component_kind: str,
) -> tuple[str, str]:
    if component_kind == "workflow":
        return policy.workflow_id, policy.workflow_version
    if component_kind == "policy":
        return policy.policy_id, policy.policy_version
    if component_kind == "schema":
        return policy.schema_id, policy.schema_version
    if component_kind == "reducer":
        return policy.handler_id, policy.handler_version
    raise ValueError(f"unsupported history component kind: {component_kind}")


def _history_record_from_migration(value: Any) -> DeterministicHistoryRecord:
    if isinstance(value, DeterministicHistoryRecord):
        value.verify_integrity()
        return value
    raw = _mapping(value, "migrated history")
    commands = raw.get("commands")
    if not isinstance(commands, list | tuple):
        raise TypeError("migrated history commands must be an array")
    return DeterministicHistoryRecord(
        schema=raw.get("schema"),
        policy=HistoryEventPolicy.from_dict(
            _mapping(raw.get("policy"), "migrated history policy")
        ),
        commands=tuple(
            DeterministicCommand.from_dict(_mapping(item, "migrated command"))
            for item in commands
        ),
        handler_input=_mapping(
            raw.get("handler_input", {}),
            "migrated history handler_input",
        ),
    )


def _audit_history_function(
    value: Any,
    *,
    field_name: str,
    parameter_count: int | None,
) -> None:
    if not isinstance(value, FunctionType):
        raise TypeError(f"{field_name} must be a plain function")
    if inspect.iscoroutinefunction(value) or inspect.isgeneratorfunction(value):
        raise TypeError(f"{field_name} must be synchronous")
    parameters = tuple(inspect.signature(value).parameters.values())
    if parameter_count is not None and (
        len(parameters) != parameter_count
        or any(
            parameter.kind
            not in {parameter.POSITIONAL_ONLY, parameter.POSITIONAL_OR_KEYWORD}
            for parameter in parameters
        )
    ):
        raise TypeError(
            f"{field_name} must accept exactly {parameter_count} positional arguments"
        )
    _audit_history_function_dependencies(value, field_name=field_name, seen=set())


def _audit_history_function_dependencies(
    function: FunctionType,
    *,
    field_name: str,
    seen: set[int],
) -> None:
    identity = id(function)
    if identity in seen:
        return
    seen.add(identity)
    closure = inspect.getclosurevars(function)
    for name in closure.builtins:
        if name not in _PURE_HISTORY_ALLOWED_BUILTINS:
            raise ValueError(f"{field_name} uses forbidden builtin: {name}")
    for name, dependency in {**closure.globals, **closure.nonlocals}.items():
        if dependency in _PURE_HISTORY_TRUSTED_FUNCTIONS:
            continue
        if isinstance(dependency, FunctionType):
            _audit_history_function_dependencies(
                dependency,
                field_name=field_name,
                seen=seen,
            )
            continue
        if (
            dependency is DeterministicCommand
            or dependency in {Mapping, CanonicalValue}
            or _is_history_immutable(dependency)
        ):
            continue
        if isinstance(dependency, ModuleType):
            kind = "module"
        else:
            kind = type(dependency).__name__
        raise ValueError(
            f"{field_name} captures forbidden dependency {name}: {kind}"
        )
    for default in function.__defaults__ or ():
        if not _is_history_immutable(default):
            raise ValueError(f"{field_name} has a mutable default")
    for default in (function.__kwdefaults__ or {}).values():
        if not _is_history_immutable(default):
            raise ValueError(f"{field_name} has a mutable default")
    _audit_history_code(
        function.__code__,
        field_name=field_name,
        seen=set(),
    )


def _audit_history_code(
    code: CodeType,
    *,
    field_name: str,
    seen: set[int],
) -> None:
    identity = id(code)
    if identity in seen:
        return
    seen.add(identity)
    for instruction in dis.get_instructions(code):
        name = str(instruction.argval) if instruction.argval is not None else ""
        if instruction.opname in _PURE_HISTORY_FORBIDDEN_OPCODES:
            raise ValueError(
                f"{field_name} uses forbidden operation: {instruction.opname}"
            )
        if name in _PURE_HISTORY_FORBIDDEN_NAMES or (
            name.startswith("__") and name.endswith("__")
        ):
            raise ValueError(f"{field_name} uses forbidden reflection name: {name}")
        if instruction.opname == "LOAD_CONST" and isinstance(
            instruction.argval,
            CodeType,
        ):
            _audit_history_code(
                instruction.argval,
                field_name=field_name,
                seen=seen,
            )


def _is_history_immutable(value: Any, *, seen: set[int] | None = None) -> bool:
    if value is None or isinstance(value, (bool, int, float, str, bytes, Enum)):
        return True
    if isinstance(value, tuple | frozenset):
        return all(_is_history_immutable(item, seen=seen) for item in value)
    if not is_dataclass(value) or isinstance(value, type):
        return False
    parameters = getattr(type(value), "__dataclass_params__", None)
    if parameters is None or not parameters.frozen:
        return False
    identities = set() if seen is None else seen
    identity = id(value)
    if identity in identities:
        return True
    identities.add(identity)
    return all(
        _is_history_immutable(getattr(value, item.name), seen=identities)
        for item in fields(value)
        if item.compare
    )


def _commands(
    values: Iterable[CanonicalDeterministicCommand],
    source: str,
) -> tuple[CanonicalDeterministicCommand, ...]:
    result = tuple(values)
    if any(not isinstance(item, CanonicalDeterministicCommand) for item in result):
        raise TypeError(f"{source} commands must be canonical deterministic commands")
    return result


def _validate_command_ordinals(
    commands: tuple[CanonicalDeterministicCommand, ...],
    first_ordinal: int,
    sequence: int,
    *,
    source: str,
) -> None:
    for offset, command in enumerate(commands):
        expected = first_ordinal + offset
        if command.ordinal != expected:
            error_type = (
                HistoryCorruptionError
                if source == "recorded"
                else HistoryCommandMismatchError
            )
            raise error_type(
                sequence=sequence,
                reason=f"{source} deterministic command order is invalid",
                details={
                    "command_index": offset,
                    "expected_ordinal": expected,
                    "actual_ordinal": command.ordinal,
                },
            )


def _mapping(value: Any, field_name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise TypeError(f"{field_name} must be an object")
    return value


def _validate_replay_event(event: Any) -> None:
    required = (
        "event_id",
        "event_type",
        "data_schema",
        "stream_id",
        "stream_sequence",
        "record_checksum",
        "payload",
    )
    if event is None or any(not hasattr(event, field_name) for field_name in required):
        raise TypeError("event must be a schema-resolved ReplayEvent")


def _string_tuple(value: Any, field_name: str) -> tuple[str, ...]:
    if not isinstance(value, list | tuple):
        raise TypeError(f"{field_name} must be an array")
    return tuple(value)


def _required_text(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} is required")
    return value.strip()


def _optional_text(value: Any, field_name: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string when supplied")
    return value.strip()


def _nonnegative_int(value: Any, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{field_name} must be a non-negative integer")
    return value


def _positive_int(value: Any, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"{field_name} must be a positive integer")
    return value


def _checksum(value: Any, field_name: str) -> str:
    text = _required_text(value, field_name)
    if not text.startswith("sha256:") or len(text) != 71:
        raise ValueError(f"{field_name} must be a sha256 checksum")
    if any(character not in "0123456789abcdef" for character in text[7:]):
        raise ValueError(f"{field_name} must be a lowercase sha256 checksum")
    return text


__all__ = [
    "CanonicalDeterministicCommand",
    "CommandComparison",
    "CommandMismatchKind",
    "DETERMINISTIC_HISTORY_EXTENSION",
    "DETERMINISTIC_HISTORY_RECORD_SCHEMA",
    "DeterministicHistoryRecord",
    "DeterministicHistoryHandler",
    "DeterministicCommand",
    "ExactVersionRegistration",
    "ExactVersionRegistry",
    "HistoryCommandMismatchError",
    "HistoryCorruptionError",
    "HistoryEventPolicy",
    "HistoryEventVerification",
    "HistoryIncompatibleVersionError",
    "HistoryMissingActivityError",
    "HistoryVerificationError",
    "HistoryVerificationSession",
    "HistoryVerificationState",
    "HistoryVerifier",
    "RecordedCommandComparator",
]
