"""Versioned checkpoints and pure replay helpers for Harness graph history.

The graph transition port remains the only durable source of truth.  This module
only validates detached checkpoint values and reduces an already-read history;
it never dispatches activities, calls a Worker, reads a clock, or appends events.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any, Protocol

from framework.events.errors import (
    EventIncompleteHistoryError,
    EventReplayMismatchError,
    EventSchemaError,
    EventStoreCorruptionError,
)
from framework.events.schema.catalog import (
    EventSchemaCatalog,
    default_event_schema_catalog,
)
from framework.harness.control_plane.errors import HarnessValidationError
from framework.harness.control_plane.event import HarnessEvent, HarnessEventType
from framework.harness.control_plane.graph_application import (
    HarnessGraphDecisionApplier,
)
from framework.harness.control_plane.graph_decision import HarnessGraphDecision
from framework.harness.control_plane.graph_evaluator import (
    HarnessGraphEvaluationContext,
)
from framework.harness.control_plane.graph_runtime import (
    HarnessGraphCommitKind,
    HarnessGraphDecisionCommit,
    HarnessGraphRecovery,
    graph_reference,
)
from framework.harness.control_plane.graph_state import (
    HarnessGraphReference,
    HarnessGraphState,
    HarnessLegacyStatusProjection,
)
from framework.harness.control_plane.scheduler import HarnessGraphStepSchedulingInput
from framework.harness.control_plane.state import HarnessStepStatus
from framework.harness.graph.canonical import canonical_checksum, required_text
from framework.harness.graph.model import NormalizedHarnessGraph
from framework.harness.graph.versioning import (
    GRAPH_ONLY_HARNESS_GRAPH_CHECKPOINT_SCHEMA,
    GRAPH_ONLY_HARNESS_GRAPH_STATE_SCHEMA,
    GRAPH_ONLY_NORMALIZED_HARNESS_GRAPH_SCHEMA,
    HARNESS_GRAPH_COMPILER_VERSION,
    HARNESS_GRAPH_CHECKPOINT_SCHEMA,
    HARNESS_GRAPH_ONLY_COMPILER_VERSION,
    HARNESS_GRAPH_CONTROL_POLICY_VERSION,
    HARNESS_GRAPH_EVALUATOR_VERSION,
    HARNESS_GRAPH_REDUCER_VERSION,
    HARNESS_GRAPH_RUNTIME_VERSION,
    HARNESS_GRAPH_STATE_SCHEMA,
    HARNESS_STEP_LIFECYCLE_VERSION,
)
from framework.harness.workflow.versioning import (
    LEGACY_CHECKPOINT_SCHEMA,
    LEGACY_EVENT_SCHEMA,
    LEGACY_STATE_SCHEMA,
)
from framework.shared.time import ensure_utc, format_datetime, parse_datetime


HARNESS_LEGACY_EVENT_EVIDENCE_SCHEMA = "newsroom.harness-legacy-event-evidence/v2"


class HarnessGraphCheckpointStore(Protocol):
    def save(
        self, checkpoint: "HarnessGraphCheckpoint"
    ) -> "HarnessGraphCheckpoint": ...

    def load(self, checkpoint_id: str) -> "HarnessGraphCheckpoint": ...


DecisionVerifier = Callable[[HarnessGraphState, HarnessGraphDecisionCommit], Any]


@dataclass(frozen=True, slots=True)
class HarnessGraphDecisionInputSnapshot:
    """Capability-free scheduler inputs captured from accepted history only."""

    graph_context: HarnessGraphEvaluationContext
    step_inputs: tuple[HarnessGraphStepSchedulingInput, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.graph_context, HarnessGraphEvaluationContext):
            raise TypeError("graph_context must be HarnessGraphEvaluationContext")
        step_inputs = tuple(self.step_inputs)
        if not all(
            isinstance(item, HarnessGraphStepSchedulingInput) for item in step_inputs
        ):
            raise TypeError(
                "step_inputs must contain HarnessGraphStepSchedulingInput values"
            )
        identities = [item.node_instance_id for item in step_inputs]
        if len(identities) != len(set(identities)):
            raise HarnessValidationError(
                "decision replay inputs contain duplicate node instances",
                code="duplicate_graph_replay_step_input",
            )
        object.__setattr__(
            self,
            "step_inputs",
            tuple(sorted(step_inputs, key=lambda item: item.node_instance_id)),
        )


@dataclass(frozen=True, slots=True)
class HarnessPinnedDecisionKernel:
    """One exact compiler/evaluator/state-machine release used by VERIFY_HISTORY.

    ``verifier`` receives only an immutable graph state and one durable decision
    commit.  Callers must resolve every nondeterministic outcome into detached
    ``HarnessGraphDecisionInputSnapshot`` values before constructing the kernel.
    The kernel itself owns no store, clock, Worker, Gate, signal, timer, or effect
    capability.
    """

    graph: NormalizedHarnessGraph
    verifier: DecisionVerifier = field(compare=False, repr=False)
    compiler_version: str | None = None
    scheduler_version: str = HARNESS_GRAPH_CONTROL_POLICY_VERSION
    evaluator_version: str = HARNESS_GRAPH_EVALUATOR_VERSION
    step_lifecycle_version: str = HARNESS_STEP_LIFECYCLE_VERSION

    def __post_init__(self) -> None:
        if not isinstance(self.graph, NormalizedHarnessGraph):
            raise TypeError("graph must be NormalizedHarnessGraph")
        if not callable(self.verifier):
            raise TypeError("verifier must be callable")
        expected_compiler_version = (
            HARNESS_GRAPH_ONLY_COMPILER_VERSION
            if self.graph.schema_version
            == GRAPH_ONLY_NORMALIZED_HARNESS_GRAPH_SCHEMA
            else HARNESS_GRAPH_COMPILER_VERSION
        )
        compiler_version = (
            expected_compiler_version
            if self.compiler_version is None
            else required_text(
                self.compiler_version,
                "decision_kernel.compiler_version",
            )
        )
        if compiler_version != expected_compiler_version:
            raise HarnessValidationError(
                "pinned decision kernel version is unavailable",
                code="unsupported_pinned_decision_kernel",
                details={"compiler_version": compiler_version},
            )
        object.__setattr__(self, "compiler_version", compiler_version)
        versions = {
            "scheduler_version": (
                self.scheduler_version,
                HARNESS_GRAPH_CONTROL_POLICY_VERSION,
            ),
            "evaluator_version": (
                self.evaluator_version,
                HARNESS_GRAPH_EVALUATOR_VERSION,
            ),
            "step_lifecycle_version": (
                self.step_lifecycle_version,
                HARNESS_STEP_LIFECYCLE_VERSION,
            ),
        }
        for field_name, (actual, supported) in versions.items():
            actual = required_text(actual, f"decision_kernel.{field_name}")
            if actual != supported:
                raise HarnessValidationError(
                    "pinned decision kernel version is unavailable",
                    code="unsupported_pinned_decision_kernel",
                    details={field_name: actual},
                )
            object.__setattr__(self, field_name, actual)
        if self.graph.compiler_version != compiler_version:
            raise HarnessValidationError(
                "pinned graph was produced by another compiler version",
                code="pinned_graph_compiler_mismatch",
            )

    def verify_graph(self, graph: NormalizedHarnessGraph) -> None:
        if not isinstance(graph, NormalizedHarnessGraph):
            raise TypeError("graph must be NormalizedHarnessGraph")
        if graph != self.graph or graph.checksum != self.graph.checksum:
            raise HarnessValidationError(
                "replay history belongs to an incompatible pinned graph",
                code="graph_replay_graph_mismatch",
            )

    def recompute(
        self,
        state: HarnessGraphState,
        commit: HarnessGraphDecisionCommit,
    ) -> HarnessGraphDecision:
        decision = commit.decision
        expected_versions = (
            (decision.scheduler_version, self.scheduler_version),
            (decision.evaluator_version, self.evaluator_version),
            (decision.step_lifecycle_version, self.step_lifecycle_version),
            (decision.graph_ref.compiler_version, self.compiler_version),
        )
        if any(actual != expected for actual, expected in expected_versions):
            raise HarnessValidationError(
                "recorded decision requires an unavailable pinned kernel",
                code="unsupported_pinned_decision_kernel",
            )
        if decision.graph_ref != graph_reference(self.graph):
            raise HarnessValidationError(
                "recorded decision belongs to another pinned graph",
                code="graph_replay_graph_mismatch",
            )
        recomputed = self.verifier(state, commit)
        if recomputed is None:
            raise EventIncompleteHistoryError(
                "pinned decision kernel has no accepted input evidence"
            )
        if not isinstance(recomputed, HarnessGraphDecision):
            raise TypeError(
                "pinned decision verifier must return HarnessGraphDecision or None"
            )
        return recomputed


@dataclass(frozen=True, slots=True)
class HarnessGraphCheckpoint:
    """A complete, detached v2 graph projection checkpoint."""

    checkpoint_id: str
    run_id: str
    graph_ref: HarnessGraphReference
    state: HarnessGraphState
    last_event_sequence: int
    projection_checksum: str
    created_at: datetime
    history_evidence_ref: str | None = None
    schema_version: str = HARNESS_GRAPH_CHECKPOINT_SCHEMA
    reducer_version: str = HARNESS_GRAPH_REDUCER_VERSION
    checkpoint_checksum: str = field(init=False)

    def __post_init__(self) -> None:
        checkpoint_id = required_text(
            self.checkpoint_id, "graph_checkpoint.checkpoint_id"
        )
        run_id = required_text(self.run_id, "graph_checkpoint.run_id")
        if not isinstance(self.graph_ref, HarnessGraphReference):
            raise TypeError("graph_ref must be HarnessGraphReference")
        if not isinstance(self.state, HarnessGraphState):
            raise TypeError("state must be HarnessGraphState")
        if self.state.run_id != run_id or self.state.graph_ref != self.graph_ref:
            raise HarnessValidationError(
                "graph checkpoint identity does not match its state",
                code="graph_checkpoint_identity_mismatch",
            )
        if (
            not isinstance(self.last_event_sequence, int)
            or isinstance(self.last_event_sequence, bool)
            or self.last_event_sequence < 1
        ):
            raise HarnessValidationError(
                "graph checkpoint last_event_sequence must be positive",
                code="invalid_graph_checkpoint_sequence",
            )
        if self.state.last_event_sequence != self.last_event_sequence:
            raise HarnessValidationError(
                "graph checkpoint sequence does not match state",
                code="graph_checkpoint_sequence_mismatch",
            )
        projection_checksum = _checksum(self.projection_checksum, "projection_checksum")
        if self.state.projection_checksum != projection_checksum:
            raise HarnessValidationError(
                "graph checkpoint projection checksum does not match state",
                code="graph_checkpoint_checksum_mismatch",
            )
        expected_checkpoint_schema = (
            GRAPH_ONLY_HARNESS_GRAPH_CHECKPOINT_SCHEMA
            if self.state.schema_version == GRAPH_ONLY_HARNESS_GRAPH_STATE_SCHEMA
            else HARNESS_GRAPH_CHECKPOINT_SCHEMA
        )
        if self.schema_version not in {
            HARNESS_GRAPH_CHECKPOINT_SCHEMA,
            GRAPH_ONLY_HARNESS_GRAPH_CHECKPOINT_SCHEMA,
        }:
            raise HarnessValidationError(
                "unsupported graph checkpoint schema",
                code="unsupported_graph_checkpoint_schema",
                details={"schema_version": str(self.schema_version)},
            )
        if self.schema_version != expected_checkpoint_schema:
            raise HarnessValidationError(
                "graph checkpoint schema does not match its Graph state",
                code="graph_checkpoint_schema_mismatch",
                details={
                    "schema_version": str(self.schema_version),
                    "expected_schema_version": expected_checkpoint_schema,
                },
            )
        if self.reducer_version != HARNESS_GRAPH_REDUCER_VERSION:
            raise HarnessValidationError(
                "unsupported graph checkpoint reducer",
                code="unsupported_graph_checkpoint_reducer",
                details={"reducer_version": str(self.reducer_version)},
            )
        created_at = _datetime(self.created_at, "graph_checkpoint.created_at")
        history_evidence_ref = _optional_checksum(
            self.history_evidence_ref,
            "history_evidence_ref",
        )
        object.__setattr__(self, "checkpoint_id", checkpoint_id)
        object.__setattr__(self, "run_id", run_id)
        object.__setattr__(self, "projection_checksum", projection_checksum)
        object.__setattr__(self, "created_at", created_at)
        object.__setattr__(self, "history_evidence_ref", history_evidence_ref)
        object.__setattr__(
            self,
            "checkpoint_checksum",
            canonical_checksum(self.checksum_projection()),
        )

    @classmethod
    def from_state(
        cls,
        checkpoint_id: str,
        state: HarnessGraphState,
        *,
        created_at: datetime,
        history_evidence_ref: str | None = None,
    ) -> "HarnessGraphCheckpoint":
        if not isinstance(state, HarnessGraphState):
            raise TypeError("state must be HarnessGraphState")
        return cls(
            checkpoint_id=checkpoint_id,
            run_id=state.run_id,
            graph_ref=state.graph_ref,
            state=state,
            last_event_sequence=state.last_event_sequence,
            projection_checksum=state.projection_checksum,
            created_at=created_at,
            history_evidence_ref=history_evidence_ref,
            schema_version=(
                GRAPH_ONLY_HARNESS_GRAPH_CHECKPOINT_SCHEMA
                if state.schema_version == GRAPH_ONLY_HARNESS_GRAPH_STATE_SCHEMA
                else HARNESS_GRAPH_CHECKPOINT_SCHEMA
            ),
        )

    def checksum_projection(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "reducer_version": self.reducer_version,
            "checkpoint_id": self.checkpoint_id,
            "run_id": self.run_id,
            "graph_ref": self.graph_ref.to_dict(),
            "state": self.state.to_dict(),
            "last_event_sequence": self.last_event_sequence,
            "projection_checksum": self.projection_checksum,
            "created_at": format_datetime(self.created_at),
            "history_evidence_ref": self.history_evidence_ref,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            **self.checksum_projection(),
            "checkpoint_checksum": self.checkpoint_checksum,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "HarnessGraphCheckpoint":
        _exact_keys(
            value,
            {
                "schema_version",
                "reducer_version",
                "checkpoint_id",
                "run_id",
                "graph_ref",
                "state",
                "last_event_sequence",
                "projection_checksum",
                "created_at",
                "history_evidence_ref",
                "checkpoint_checksum",
            },
            "graph checkpoint",
        )
        checkpoint = cls(
            checkpoint_id=value["checkpoint_id"],
            run_id=value["run_id"],
            graph_ref=HarnessGraphReference.from_dict(value["graph_ref"]),
            state=HarnessGraphState.from_dict(value["state"]),
            last_event_sequence=value["last_event_sequence"],
            projection_checksum=value["projection_checksum"],
            created_at=parse_datetime(value["created_at"]),
            history_evidence_ref=value["history_evidence_ref"],
            schema_version=value["schema_version"],
            reducer_version=value["reducer_version"],
        )
        if value["checkpoint_checksum"] != checkpoint.checkpoint_checksum:
            raise HarnessValidationError(
                "graph checkpoint checksum does not match its content",
                code="graph_checkpoint_checksum_mismatch",
            )
        return checkpoint


class InMemoryHarnessGraphCheckpointStore:
    """Small deterministic store used by framework composition and tests."""

    def __init__(self) -> None:
        self._checkpoints: dict[str, HarnessGraphCheckpoint] = {}

    def save(self, checkpoint: HarnessGraphCheckpoint) -> HarnessGraphCheckpoint:
        if not isinstance(checkpoint, HarnessGraphCheckpoint):
            raise TypeError("checkpoint must be HarnessGraphCheckpoint")
        existing = self._checkpoints.get(checkpoint.checkpoint_id)
        if existing is not None and existing != checkpoint:
            raise HarnessValidationError(
                "checkpoint identity already contains different content",
                code="graph_checkpoint_conflict",
            )
        self._checkpoints[checkpoint.checkpoint_id] = checkpoint
        return checkpoint

    def load(self, checkpoint_id: str) -> HarnessGraphCheckpoint:
        checkpoint_id = required_text(checkpoint_id, "checkpoint_id")
        try:
            return self._checkpoints[checkpoint_id]
        except KeyError as exc:
            raise HarnessValidationError(
                "graph checkpoint was not found",
                code="graph_checkpoint_not_found",
                details={"checkpoint_id": checkpoint_id},
            ) from exc


@dataclass(frozen=True, slots=True)
class HarnessGraphCheckpointReadResult:
    source_schema: str
    checkpoint: HarnessGraphCheckpoint | None = None
    applied_upcasters: tuple[str, ...] = ()
    quarantine_reason: str | None = None

    @property
    def quarantined(self) -> bool:
        return self.quarantine_reason is not None


@dataclass(frozen=True, slots=True)
class HarnessGraphStateReadResult:
    source_schema: str
    state: HarnessGraphState | None = None
    source_checksum: str | None = None
    history_evidence_ref: str | None = None
    applied_upcasters: tuple[str, ...] = ()
    quarantine_reason: str | None = None

    @property
    def quarantined(self) -> bool:
        return self.quarantine_reason is not None


class HarnessGraphStateReader:
    """Strict normalized-Graph state reader and legacy cursor upcaster."""

    def read(
        self,
        value: Mapping[str, Any],
        *,
        expected_graph_ref: HarnessGraphReference | None = None,
    ) -> HarnessGraphState:
        if not isinstance(value, Mapping):
            raise HarnessValidationError(
                "graph state must be an object",
                code="invalid_graph_state_projection",
            )
        if value.get("schema_version") not in {
            HARNESS_GRAPH_STATE_SCHEMA,
            GRAPH_ONLY_HARNESS_GRAPH_STATE_SCHEMA,
        }:
            raise HarnessValidationError(
                "graph state requires an explicit supported schema",
                code="unsupported_graph_state_schema",
            )
        state = HarnessGraphState.from_dict(value)
        if expected_graph_ref is not None and state.graph_ref != expected_graph_ref:
            raise HarnessValidationError(
                "graph state belongs to an incompatible graph",
                code="graph_state_graph_mismatch",
            )
        return state

    def upcast_legacy(
        self,
        value: Mapping[str, Any],
        *,
        rebuilt_state: HarnessGraphState,
        history_evidence_ref: str,
    ) -> HarnessGraphStateReadResult:
        if not isinstance(value, Mapping):
            raise HarnessValidationError(
                "legacy Harness state must be an object",
                code="invalid_legacy_graph_state",
            )
        if value.get("schema_version") != LEGACY_STATE_SCHEMA:
            raise HarnessValidationError(
                "legacy Harness state schema is unsupported",
                code="unsupported_legacy_state_schema",
            )
        _exact_keys(
            value,
            {
                "schema_version",
                "run_spec",
                "status",
                "step_states",
                "current_step_id",
                "turn_count",
                "replan_count",
                "worker_call_count",
                "metadata",
                "updated_at",
            },
            "legacy Harness state",
        )
        evidence_ref = _checksum(
            history_evidence_ref,
            "history_evidence_ref",
        )
        run_spec = _mapping(value["run_spec"], "legacy_state.run_spec")
        run_id = required_text(run_spec.get("run_id"), "legacy_state.run_id")
        if rebuilt_state.run_id != run_id:
            raise HarnessValidationError(
                "legacy state and rebuilt history belong to different runs",
                code="graph_state_history_mismatch",
            )
        expected_run_spec_ref = rebuilt_state.metadata.get("run_spec_checksum")
        if (
            not isinstance(expected_run_spec_ref, str)
            or canonical_checksum(dict(run_spec)) != expected_run_spec_ref
        ):
            raise HarnessValidationError(
                "legacy state run specification conflicts with rebuilt history",
                code="graph_state_history_mismatch",
            )
        metadata = _mapping(value["metadata"], "legacy_state.metadata")
        _validate_legacy_state_shape(value, run_spec=run_spec)
        projection = HarnessLegacyStatusProjection(
            value["status"],
            resumable_blocked=metadata.get("resumable_blocked") is True,
            indeterminate_evidence_ref=metadata.get("indeterminate_evidence_ref"),
        )
        if (
            projection.lifecycle is not rebuilt_state.lifecycle
            or projection.outcome is not rebuilt_state.outcome
        ):
            raise HarnessValidationError(
                "legacy status conflicts with rebuilt graph history",
                code="legacy_state_projection_mismatch",
            )
        legacy_counters = {
            "turns": value["turn_count"],
            "replans": value["replan_count"],
            "worker_calls": value["worker_call_count"],
        }
        for counter_name, raw_used in legacy_counters.items():
            if (
                not isinstance(raw_used, int)
                or isinstance(raw_used, bool)
                or raw_used < 0
                or rebuilt_state.budgets.require(counter_name).used != raw_used
            ):
                raise HarnessValidationError(
                    "legacy counters conflict with rebuilt graph history",
                    code="legacy_state_projection_mismatch",
                    details={"counter": counter_name},
                )
        return HarnessGraphStateReadResult(
            source_schema=LEGACY_STATE_SCHEMA,
            state=rebuilt_state,
            source_checksum=canonical_checksum(dict(value)),
            history_evidence_ref=evidence_ref,
            applied_upcasters=(f"{LEGACY_STATE_SCHEMA}->{HARNESS_GRAPH_STATE_SCHEMA}",),
        )

    def read_or_quarantine(
        self,
        value: Mapping[str, Any],
        *,
        expected_graph_ref: HarnessGraphReference | None = None,
        rebuilt_state: HarnessGraphState | None = None,
        history_evidence_ref: str | None = None,
    ) -> HarnessGraphStateReadResult:
        source_schema = _source_schema(value)
        try:
            if source_schema == LEGACY_STATE_SCHEMA:
                if rebuilt_state is None or history_evidence_ref is None:
                    raise HarnessValidationError(
                        "legacy graph state requires rebuilt history evidence",
                        code="graph_history_evidence_missing",
                    )
                result = self.upcast_legacy(
                    value,
                    rebuilt_state=rebuilt_state,
                    history_evidence_ref=history_evidence_ref,
                )
                if (
                    expected_graph_ref is not None
                    and result.state is not None
                    and result.state.graph_ref != expected_graph_ref
                ):
                    raise HarnessValidationError(
                        "upcast graph state belongs to an incompatible graph",
                        code="graph_state_graph_mismatch",
                    )
                return result
            state = self.read(value, expected_graph_ref=expected_graph_ref)
        except (HarnessValidationError, TypeError, ValueError) as exc:
            return HarnessGraphStateReadResult(
                source_schema=source_schema,
                quarantine_reason=_quarantine_code(
                    exc,
                    fallback="invalid_graph_state_projection",
                ),
            )
        return HarnessGraphStateReadResult(
            source_schema=source_schema,
            state=state,
            source_checksum=canonical_checksum(dict(value)),
        )


class HarnessLegacyEventCategory(StrEnum):
    INITIALIZATION = "initialization"
    DECISION = "decision"
    PROJECTION = "projection"
    ACTIVITY_RESULT = "activity_result"
    OBSERVATION = "observation"
    DIAGNOSTIC = "diagnostic"


_LEGACY_EVENT_CATEGORIES = {
    HarnessEventType.RUN_CREATED: HarnessLegacyEventCategory.INITIALIZATION,
    HarnessEventType.DECISION_RECORDED: HarnessLegacyEventCategory.DECISION,
    HarnessEventType.TRANSITION_COMMITTED: HarnessLegacyEventCategory.PROJECTION,
    HarnessEventType.RUN_STATE_CHANGED: HarnessLegacyEventCategory.PROJECTION,
    HarnessEventType.STEP_STATE_CHANGED: HarnessLegacyEventCategory.PROJECTION,
    HarnessEventType.WORKER_RESULT_RECORDED: HarnessLegacyEventCategory.ACTIVITY_RESULT,
    HarnessEventType.GATE_EVALUATED: HarnessLegacyEventCategory.OBSERVATION,
    HarnessEventType.PHASE_RECORDED: HarnessLegacyEventCategory.DIAGNOSTIC,
    HarnessEventType.WORKER_CALLED: HarnessLegacyEventCategory.DIAGNOSTIC,
    HarnessEventType.CHECKPOINT_CREATED: HarnessLegacyEventCategory.DIAGNOSTIC,
}


@dataclass(frozen=True, slots=True)
class HarnessLegacyEventEvidence:
    event_id: str
    run_id: str
    stream_sequence: int
    event_type: HarnessEventType | str
    category: HarnessLegacyEventCategory | str
    source_event_checksum: str
    history_evidence_ref: str
    occurred_at: datetime
    source_schema: str = LEGACY_EVENT_SCHEMA
    schema_version: str = HARNESS_LEGACY_EVENT_EVIDENCE_SCHEMA
    evidence_checksum: str = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "event_id", required_text(self.event_id, "event_id"))
        object.__setattr__(self, "run_id", required_text(self.run_id, "run_id"))
        _positive_int(self.stream_sequence, "stream_sequence")
        event_type = HarnessEventType(self.event_type)
        category = HarnessLegacyEventCategory(self.category)
        if _LEGACY_EVENT_CATEGORIES[event_type] is not category:
            raise HarnessValidationError(
                "legacy event category does not match its event type",
                code="legacy_event_category_mismatch",
            )
        if self.source_schema != LEGACY_EVENT_SCHEMA:
            raise HarnessValidationError(
                "legacy event evidence uses an unsupported source schema",
                code="unsupported_legacy_event_schema",
            )
        if self.schema_version != HARNESS_LEGACY_EVENT_EVIDENCE_SCHEMA:
            raise HarnessValidationError(
                "legacy event evidence schema is unsupported",
                code="unsupported_legacy_event_evidence_schema",
            )
        object.__setattr__(
            self,
            "source_event_checksum",
            _checksum(self.source_event_checksum, "source_event_checksum"),
        )
        object.__setattr__(
            self,
            "history_evidence_ref",
            _checksum(self.history_evidence_ref, "history_evidence_ref"),
        )
        object.__setattr__(self, "event_type", event_type)
        object.__setattr__(self, "category", category)
        object.__setattr__(
            self, "occurred_at", _datetime(self.occurred_at, "occurred_at")
        )
        object.__setattr__(
            self,
            "evidence_checksum",
            canonical_checksum(self.checksum_projection()),
        )

    def checksum_projection(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "source_schema": self.source_schema,
            "event_id": self.event_id,
            "run_id": self.run_id,
            "stream_sequence": self.stream_sequence,
            "event_type": self.event_type.value,
            "category": self.category.value,
            "source_event_checksum": self.source_event_checksum,
            "history_evidence_ref": self.history_evidence_ref,
            "occurred_at": format_datetime(self.occurred_at),
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            **self.checksum_projection(),
            "evidence_checksum": self.evidence_checksum,
        }


@dataclass(frozen=True, slots=True)
class HarnessLegacyEventReadResult:
    source_schema: str
    evidence: HarnessLegacyEventEvidence | None = None
    applied_upcasters: tuple[str, ...] = ()
    quarantine_reason: str | None = None

    @property
    def quarantined(self) -> bool:
        return self.quarantine_reason is not None


class HarnessLegacyEventReader:
    """Upcast v1 events to reference-only evidence, never executable commands."""

    def __init__(self, schema_catalog: EventSchemaCatalog | None = None) -> None:
        if schema_catalog is not None and not isinstance(
            schema_catalog,
            EventSchemaCatalog,
        ):
            raise TypeError("schema_catalog must be EventSchemaCatalog")
        self._schema_catalog = schema_catalog or default_event_schema_catalog()

    def upcast(
        self,
        value: Mapping[str, Any],
        *,
        stream_sequence: int,
        history_evidence_ref: str,
        expected_run_id: str | None = None,
    ) -> HarnessLegacyEventReadResult:
        if not isinstance(value, Mapping):
            raise HarnessValidationError(
                "legacy Harness event must be an object",
                code="invalid_legacy_event",
            )
        if value.get("schema_version") != LEGACY_EVENT_SCHEMA:
            raise HarnessValidationError(
                "legacy Harness event schema is unsupported",
                code="unsupported_legacy_event_schema",
            )
        event_value = dict(value)
        event_value.pop("schema_version")
        event = HarnessEvent.from_dict(event_value)
        self._schema_catalog.validate(
            event.event_type.value,
            LEGACY_EVENT_SCHEMA,
            event.payload,
        )
        if expected_run_id is not None and event.run_id != required_text(
            expected_run_id,
            "expected_run_id",
        ):
            raise HarnessValidationError(
                "legacy event belongs to another run",
                code="legacy_event_run_mismatch",
            )
        evidence_ref = _checksum(history_evidence_ref, "history_evidence_ref")
        source_checksum = canonical_checksum(dict(value))
        evidence = HarnessLegacyEventEvidence(
            event_id=event.event_id or "",
            run_id=event.run_id,
            stream_sequence=_positive_int(stream_sequence, "stream_sequence"),
            event_type=event.event_type,
            category=_LEGACY_EVENT_CATEGORIES[event.event_type],
            source_event_checksum=source_checksum,
            history_evidence_ref=evidence_ref,
            occurred_at=event.occurred_at,
        )
        return HarnessLegacyEventReadResult(
            source_schema=LEGACY_EVENT_SCHEMA,
            evidence=evidence,
            applied_upcasters=(
                f"{LEGACY_EVENT_SCHEMA}->{HARNESS_LEGACY_EVENT_EVIDENCE_SCHEMA}",
            ),
        )

    def read_or_quarantine(
        self,
        value: Mapping[str, Any],
        *,
        stream_sequence: int,
        history_evidence_ref: str | None,
        expected_run_id: str | None = None,
    ) -> HarnessLegacyEventReadResult:
        source_schema = _source_schema(value)
        try:
            if history_evidence_ref is None:
                raise HarnessValidationError(
                    "legacy event requires rebuilt graph history evidence",
                    code="graph_history_evidence_missing",
                )
            return self.upcast(
                value,
                stream_sequence=stream_sequence,
                history_evidence_ref=history_evidence_ref,
                expected_run_id=expected_run_id,
            )
        except (HarnessValidationError, EventSchemaError, TypeError, ValueError) as exc:
            return HarnessLegacyEventReadResult(
                source_schema=source_schema,
                quarantine_reason=(
                    "legacy_event_schema_validation_failed"
                    if isinstance(exc, EventSchemaError)
                    else _quarantine_code(
                        exc,
                        fallback="invalid_legacy_event",
                    )
                ),
            )


class HarnessGraphCheckpointReader:
    """Strict normalized-Graph reader plus legacy checkpoint upcaster."""

    def read(
        self,
        value: Mapping[str, Any],
        *,
        expected_graph_ref: HarnessGraphReference | None = None,
    ) -> HarnessGraphCheckpoint:
        if not isinstance(value, Mapping):
            raise HarnessValidationError(
                "graph checkpoint must be an object",
                code="invalid_graph_checkpoint",
            )
        schema = value.get("schema_version")
        if schema not in {
            HARNESS_GRAPH_CHECKPOINT_SCHEMA,
            GRAPH_ONLY_HARNESS_GRAPH_CHECKPOINT_SCHEMA,
        }:
            raise HarnessValidationError(
                "checkpoint requires an explicit supported schema",
                code="unsupported_graph_checkpoint_schema",
                details={"schema_version": str(schema)},
            )
        checkpoint = HarnessGraphCheckpoint.from_dict(value)
        if (
            expected_graph_ref is not None
            and checkpoint.graph_ref != expected_graph_ref
        ):
            raise HarnessValidationError(
                "checkpoint belongs to an incompatible graph",
                code="graph_checkpoint_graph_mismatch",
            )
        return checkpoint

    def upcast_legacy(
        self,
        value: Mapping[str, Any],
        *,
        rebuilt_state: HarnessGraphState,
        last_event_sequence: int,
        history_evidence_ref: str,
    ) -> HarnessGraphCheckpointReadResult:
        if not isinstance(value, Mapping):
            raise HarnessValidationError(
                "legacy checkpoint must be an object",
                code="invalid_legacy_graph_checkpoint",
            )
        if value.get("schema_version") != LEGACY_CHECKPOINT_SCHEMA:
            raise HarnessValidationError(
                "legacy checkpoint schema is unsupported",
                code="unsupported_graph_checkpoint_schema",
                details={"schema_version": str(value.get("schema_version"))},
            )
        required = {
            "schema_version",
            "checkpoint_id",
            "run_id",
            "state",
            "last_event_id",
            "checksum",
            "artifact_refs",
            "metadata",
            "created_at",
        }
        _exact_keys(value, required, "legacy graph checkpoint")
        state_value = value["state"]
        if not isinstance(state_value, Mapping):
            raise HarnessValidationError(
                "legacy checkpoint state must be an object",
                code="invalid_legacy_graph_checkpoint",
            )
        run_id = required_text(value["run_id"], "legacy_checkpoint.run_id")
        if rebuilt_state.run_id != run_id:
            raise HarnessValidationError(
                "legacy checkpoint and rebuilt history belong to different runs",
                code="graph_checkpoint_history_mismatch",
            )
        state_upcast = HarnessGraphStateReader().upcast_legacy(
            {"schema_version": LEGACY_STATE_SCHEMA, **dict(state_value)},
            rebuilt_state=rebuilt_state,
            history_evidence_ref=history_evidence_ref,
        )
        if state_upcast.state != rebuilt_state:
            raise HarnessValidationError(
                "legacy checkpoint state conflicts with rebuilt history",
                code="legacy_checkpoint_projection_mismatch",
            )
        from framework.harness.runtime.checkpoint import checkpoint_checksum

        expected_legacy_checksum = checkpoint_checksum(
            run_id,
            dict(state_value),
            value["last_event_id"],
        )
        if value["checksum"] != expected_legacy_checksum:
            raise HarnessValidationError(
                "legacy checkpoint checksum is invalid",
                code="legacy_checkpoint_checksum_mismatch",
            )
        checkpoint = HarnessGraphCheckpoint.from_state(
            value["checkpoint_id"],
            rebuilt_state,
            created_at=parse_datetime(value["created_at"]),
            history_evidence_ref=history_evidence_ref,
        )
        if checkpoint.last_event_sequence != _positive_int(
            last_event_sequence,
            "last_event_sequence",
        ):
            raise HarnessValidationError(
                "rebuilt history does not end at the declared upcast sequence",
                code="legacy_checkpoint_sequence_mismatch",
            )
        return HarnessGraphCheckpointReadResult(
            source_schema=LEGACY_CHECKPOINT_SCHEMA,
            checkpoint=checkpoint,
            applied_upcasters=(
                f"{LEGACY_CHECKPOINT_SCHEMA}->{HARNESS_GRAPH_CHECKPOINT_SCHEMA}",
            ),
        )

    def read_or_quarantine(
        self,
        value: Mapping[str, Any],
        *,
        expected_graph_ref: HarnessGraphReference | None = None,
        rebuilt_state: HarnessGraphState | None = None,
        last_event_sequence: int | None = None,
        history_evidence_ref: str | None = None,
    ) -> HarnessGraphCheckpointReadResult:
        source_schema = _source_schema(value)
        try:
            if source_schema == LEGACY_CHECKPOINT_SCHEMA:
                if (
                    rebuilt_state is None
                    or last_event_sequence is None
                    or history_evidence_ref is None
                ):
                    raise HarnessValidationError(
                        "legacy checkpoint requires rebuilt history evidence",
                        code="graph_history_evidence_missing",
                    )
                result = self.upcast_legacy(
                    value,
                    rebuilt_state=rebuilt_state,
                    last_event_sequence=last_event_sequence,
                    history_evidence_ref=history_evidence_ref,
                )
                if (
                    expected_graph_ref is not None
                    and result.checkpoint is not None
                    and result.checkpoint.graph_ref != expected_graph_ref
                ):
                    raise HarnessValidationError(
                        "upcast checkpoint belongs to an incompatible graph",
                        code="graph_checkpoint_graph_mismatch",
                    )
                return result
            checkpoint = self.read(
                value,
                expected_graph_ref=expected_graph_ref,
            )
        except (HarnessValidationError, TypeError, ValueError) as exc:
            return HarnessGraphCheckpointReadResult(
                source_schema=source_schema,
                quarantine_reason=_quarantine_code(
                    exc,
                    fallback="invalid_graph_checkpoint",
                ),
            )
        return HarnessGraphCheckpointReadResult(
            source_schema=source_schema,
            checkpoint=checkpoint,
        )


@dataclass(frozen=True, slots=True)
class HarnessGraphReplayReport:
    run_id: str
    mode: str
    state: HarnessGraphState
    through_sequence: int
    projection_checksum: str
    verified_decision_checksums: tuple[str, ...] = ()
    applied_projection_sequences: tuple[int, ...] = ()
    pending_cause_checksums: tuple[str, ...] = ()
    quarantine_reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": HARNESS_GRAPH_RUNTIME_VERSION,
            "run_id": self.run_id,
            "mode": self.mode,
            "state": self.state.to_dict(),
            "through_sequence": self.through_sequence,
            "projection_checksum": self.projection_checksum,
            "verified_decision_checksums": list(self.verified_decision_checksums),
            "applied_projection_sequences": list(self.applied_projection_sequences),
            "pending_cause_checksums": list(self.pending_cause_checksums),
            "quarantine_reason": self.quarantine_reason,
        }


@dataclass(frozen=True, slots=True)
class HarnessGraphReplayReadResult:
    report: HarnessGraphReplayReport | None = None
    quarantine_reason: str | None = None
    sequence: int | None = None

    @property
    def quarantined(self) -> bool:
        return self.quarantine_reason is not None


class HarnessGraphHistoryReducer:
    """Pure reducer/verifier over the canonical graph recovery facts."""

    def __init__(self, applier: HarnessGraphDecisionApplier | None = None) -> None:
        self._applier = applier or HarnessGraphDecisionApplier()

    def rebuild(
        self,
        recovery: HarnessGraphRecovery,
        *,
        checkpoint: HarnessGraphCheckpoint | None = None,
        through_sequence: int | None = None,
        decision_kernel: HarnessPinnedDecisionKernel | None = None,
        verify_history: bool = False,
    ) -> HarnessGraphReplayReport:
        if not isinstance(recovery, HarnessGraphRecovery):
            raise TypeError("recovery must be HarnessGraphRecovery")
        if recovery.state is None or recovery.graph is None:
            raise EventIncompleteHistoryError(
                "graph history has no initialized projection"
            )
        if verify_history:
            if decision_kernel is None:
                raise EventIncompleteHistoryError(
                    "VERIFY_HISTORY requires one pinned decision kernel"
                )
            decision_kernel.verify_graph(recovery.graph)
        verified_prefix: tuple[str, ...] = ()
        if checkpoint is not None:
            if (
                checkpoint.run_id != recovery.run_id
                or checkpoint.graph_ref != graph_reference(recovery.graph)
            ):
                raise HarnessValidationError(
                    "checkpoint is incompatible with graph history",
                    code="graph_checkpoint_history_mismatch",
                )
            if checkpoint.last_event_sequence > recovery.expected_last_sequence:
                raise HarnessValidationError(
                    "checkpoint is ahead of graph history",
                    code="graph_checkpoint_ahead_of_history",
                )
            checkpoint_projection = next(
                (
                    item
                    for item in recovery.projection_commits
                    if item.sequence == checkpoint.last_event_sequence
                ),
                None,
            )
            if (
                checkpoint_projection is None
                or checkpoint_projection.state.projection_checksum
                != checkpoint.projection_checksum
            ):
                raise HarnessValidationError(
                    "checkpoint is not an exact prefix of graph history",
                    code="graph_checkpoint_history_mismatch",
                )
            if verify_history:
                expected_evidence = graph_history_evidence_ref(
                    recovery,
                    through_sequence=checkpoint.last_event_sequence,
                    projection_checksum=checkpoint.projection_checksum,
                )
                if checkpoint.history_evidence_ref is None:
                    raise EventIncompleteHistoryError(
                        "VERIFY_HISTORY checkpoint is missing prefix evidence"
                    )
                if checkpoint.history_evidence_ref != expected_evidence:
                    raise EventReplayMismatchError(
                        sequence=checkpoint.last_event_sequence,
                        reason="checkpoint history evidence does not match its prefix",
                    )
                assert decision_kernel is not None
                prefix = self.rebuild(
                    recovery,
                    through_sequence=checkpoint.last_event_sequence,
                    decision_kernel=decision_kernel,
                    verify_history=True,
                )
                if (
                    prefix.state != checkpoint.state
                    or prefix.projection_checksum != checkpoint.projection_checksum
                ):
                    raise EventReplayMismatchError(
                        sequence=checkpoint.last_event_sequence,
                        reason="verified history prefix differs from checkpoint state",
                    )
                verified_prefix = prefix.verified_decision_checksums
            state = checkpoint.state
            start_sequence = checkpoint.last_event_sequence
        else:
            initialization = next(
                (
                    item
                    for item in recovery.projection_commits
                    if item.commit_kind is HarnessGraphCommitKind.INITIALIZE
                ),
                None,
            )
            if initialization is None:
                raise EventIncompleteHistoryError(
                    "graph history is missing initialization"
                )
            state = initialization.state
            start_sequence = initialization.sequence
        target_sequence = (
            recovery.expected_last_sequence
            if through_sequence is None
            else _positive_int(through_sequence, "through_sequence")
        )
        if target_sequence > recovery.expected_last_sequence:
            raise HarnessValidationError(
                "replay target is ahead of canonical stream",
                code="graph_replay_high_watermark_mismatch",
            )
        if target_sequence < start_sequence:
            raise HarnessValidationError(
                "replay target precedes its checkpoint",
                code="graph_replay_high_watermark_mismatch",
            )
        decisions = {item.sequence: item for item in recovery.decision_commits}
        results = {item.sequence: item for item in recovery.activity_result_commits}
        observations = {item.sequence: item for item in recovery.observation_commits}
        projections = {
            item.sequence: item
            for item in recovery.projection_commits
            if start_sequence < item.sequence <= target_sequence
        }
        activities = {item.activity_id: item for item in recovery.activities}
        verified_decisions: list[str] = list(verified_prefix)
        applied_sequences: list[int] = []
        for projection_sequence in sorted(projections):
            causal_sequence = projection_sequence - 1
            if causal_sequence <= start_sequence:
                raise EventReplayMismatchError(
                    sequence=causal_sequence,
                    reason="checkpoint projection chain overlaps its starting state",
                )
            projection = projections[projection_sequence]
            if causal_sequence in decisions:
                commit = decisions[causal_sequence]
                if verify_history:
                    _verify_decision_identity(state, commit)
                    assert decision_kernel is not None
                    recomputed = decision_kernel.recompute(state, commit)
                    if recomputed != commit.decision:
                        raise EventReplayMismatchError(
                            sequence=commit.sequence,
                            reason=(
                                "pinned decision kernel differs from recorded history"
                            ),
                        )
                applied = self._applier.apply(
                    state,
                    recovery.graph,
                    commit.decision,
                    decision_sequence=commit.sequence,
                    projection_sequence=projection.sequence,
                    activity_input_ref=commit.activity_input_ref,
                    accepted_evidence_refs=commit.accepted_evidence_refs,
                    side_effect_outcome_ref=commit.side_effect_outcome_ref,
                )
                if (
                    applied.state != projection.state
                    or applied.state.projection_checksum
                    != projection.state.projection_checksum
                ):
                    raise EventReplayMismatchError(
                        sequence=projection.sequence,
                        reason="graph decision reducer checksum differs from history",
                    )
                if verify_history:
                    verified_decisions.append(commit.decision.decision_checksum)
            elif causal_sequence in results:
                commit = results[causal_sequence]
                activity = activities.get(commit.result.activity_id)
                if activity is None:
                    raise EventIncompleteHistoryError(
                        "graph activity result has no durable activity descriptor"
                    )
                applied_state = self._applier.apply_activity_result(
                    state,
                    activity,
                    commit.result,
                    result_sequence=commit.sequence,
                    projection_sequence=projection.sequence,
                )
                if applied_state != projection.state:
                    raise EventReplayMismatchError(
                        sequence=projection.sequence,
                        reason="graph activity-result reducer checksum differs from history",
                    )
            elif causal_sequence in observations:
                commit = observations[causal_sequence]
                applied_state = self._applier.apply_observation(
                    state,
                    recovery.graph,
                    commit.observation,
                    observation_sequence=commit.sequence,
                    projection_sequence=projection.sequence,
                )
                if applied_state != projection.state:
                    raise EventReplayMismatchError(
                        sequence=projection.sequence,
                        reason="graph observation reducer checksum differs from history",
                    )
            else:
                raise EventIncompleteHistoryError(
                    "graph projection has no causal record",
                )
            state = projection.state
            applied_sequences.append(projection.sequence)
        pending_decisions = tuple(
            item
            for item in recovery.decision_commits
            if start_sequence < item.sequence <= target_sequence
            and item.sequence + 1 not in projections
        )
        if verify_history:
            assert decision_kernel is not None
            for commit in pending_decisions:
                _verify_decision_identity(state, commit)
                recomputed = decision_kernel.recompute(state, commit)
                if recomputed != commit.decision:
                    raise EventReplayMismatchError(
                        sequence=commit.sequence,
                        reason="pinned decision kernel differs from recorded history",
                    )
                verified_decisions.append(commit.decision.decision_checksum)
        pending = tuple(
            sorted(
                (
                    *(
                        item.decision.decision_checksum
                        for item in recovery.decision_commits
                        if start_sequence < item.sequence <= target_sequence
                        and item.sequence + 1 not in projections
                    ),
                    *(
                        item.result.result_checksum
                        for item in recovery.activity_result_commits
                        if start_sequence < item.sequence <= target_sequence
                        and item.sequence + 1 not in projections
                    ),
                    *(
                        item.observation.observation_checksum
                        for item in recovery.observation_commits
                        if start_sequence < item.sequence <= target_sequence
                        and item.sequence + 1 not in projections
                    ),
                )
            )
        )
        return HarnessGraphReplayReport(
            run_id=recovery.run_id,
            mode="verify_history" if verify_history else "rebuild_state",
            state=state,
            through_sequence=target_sequence,
            projection_checksum=state.projection_checksum,
            verified_decision_checksums=tuple(verified_decisions),
            applied_projection_sequences=tuple(applied_sequences),
            pending_cause_checksums=pending,
        )

    def rebuild_or_quarantine(
        self,
        recovery: HarnessGraphRecovery,
        **kwargs: Any,
    ) -> HarnessGraphReplayReadResult:
        try:
            report = self.rebuild(recovery, **kwargs)
        except (
            EventIncompleteHistoryError,
            EventReplayMismatchError,
            EventStoreCorruptionError,
            HarnessValidationError,
            TypeError,
            ValueError,
        ) as exc:
            return quarantine_graph_replay_failure(exc)
        return HarnessGraphReplayReadResult(report=report)


def _verify_decision_identity(
    state: HarnessGraphState,
    commit: HarnessGraphDecisionCommit,
) -> None:
    decision = commit.decision
    if decision.input_projection_checksum != state.projection_checksum:
        raise EventReplayMismatchError(
            sequence=commit.sequence,
            reason="recorded graph decision input checksum does not match replay state",
        )
    if canonical_checksum(decision.checksum_projection()) != decision.decision_checksum:
        raise EventReplayMismatchError(
            sequence=commit.sequence,
            reason="recorded graph decision checksum is invalid",
        )


def graph_history_evidence_ref(
    recovery: HarnessGraphRecovery,
    *,
    through_sequence: int,
    projection_checksum: str,
) -> str:
    """Return the deterministic evidence ref for one verified history prefix."""

    if not isinstance(recovery, HarnessGraphRecovery):
        raise TypeError("recovery must be HarnessGraphRecovery")
    sequence = _positive_int(through_sequence, "through_sequence")
    projection_ref = _checksum(projection_checksum, "projection_checksum")
    if sequence > recovery.expected_last_sequence:
        raise HarnessValidationError(
            "history evidence prefix is ahead of the canonical stream",
            code="graph_replay_high_watermark_mismatch",
        )
    decisions = [
        {
            "sequence": item.sequence,
            "checksum": item.decision.decision_checksum,
        }
        for item in recovery.decision_commits
        if item.sequence <= sequence
    ]
    results = [
        {
            "sequence": item.sequence,
            "checksum": item.result.result_checksum,
        }
        for item in recovery.activity_result_commits
        if item.sequence <= sequence
    ]
    observations = [
        {
            "sequence": item.sequence,
            "checksum": item.observation.observation_checksum,
        }
        for item in recovery.observation_commits
        if item.sequence <= sequence
    ]
    return canonical_checksum(
        {
            "run_id": recovery.run_id,
            "graph_checksum": (
                None if recovery.graph is None else recovery.graph.checksum
            ),
            "through_sequence": sequence,
            "projection_checksum": projection_ref,
            "decisions": decisions,
            "activity_results": results,
            "observations": observations,
        }
    )


def quarantine_graph_replay_failure(exc: Exception) -> HarnessGraphReplayReadResult:
    """Convert a bounded replay/read failure into a payload-free quarantine fact."""

    if isinstance(exc, EventIncompleteHistoryError):
        return HarnessGraphReplayReadResult(
            quarantine_reason="graph_history_evidence_missing",
            sequence=getattr(exc, "sequence", None),
        )
    if isinstance(exc, EventReplayMismatchError):
        return HarnessGraphReplayReadResult(
            quarantine_reason="graph_history_verification_mismatch",
            sequence=exc.sequence,
        )
    if isinstance(exc, EventStoreCorruptionError):
        return HarnessGraphReplayReadResult(
            quarantine_reason="corrupt_graph_history",
        )
    if isinstance(exc, HarnessValidationError):
        return HarnessGraphReplayReadResult(
            quarantine_reason=_history_quarantine_code(exc),
        )
    if isinstance(exc, (TypeError, ValueError)):
        return HarnessGraphReplayReadResult(
            quarantine_reason="corrupt_graph_history",
        )
    raise TypeError("unsupported graph replay quarantine failure") from exc


def _exact_keys(value: Mapping[str, Any], expected: set[str], label: str) -> None:
    if not isinstance(value, Mapping):
        raise HarnessValidationError(
            f"{label} must be an object", code="invalid_graph_checkpoint"
        )
    actual = set(value)
    if actual != expected:
        raise HarnessValidationError(
            f"{label} has invalid fields",
            code="invalid_graph_checkpoint",
            details={
                "missing": sorted(expected - actual),
                "unknown": sorted(actual - expected),
            },
        )


def _mapping(value: Any, field_name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise HarnessValidationError(
            f"{field_name} must be an object",
            code="invalid_graph_history_record",
        )
    return value


def _validate_legacy_state_shape(
    value: Mapping[str, Any],
    *,
    run_spec: Mapping[str, Any],
) -> None:
    workflow = _mapping(run_spec.get("workflow"), "legacy_state.workflow")
    declared_steps_value = workflow.get("steps")
    if not isinstance(declared_steps_value, (list, tuple)):
        raise HarnessValidationError(
            "legacy workflow steps must be an array",
            code="invalid_legacy_graph_state",
        )
    declared_step_ids = tuple(
        required_text(
            _mapping(item, "legacy_state.workflow.step").get("step_id"),
            "legacy_state.workflow.step_id",
        )
        for item in declared_steps_value
    )
    raw_steps = value["step_states"]
    if not isinstance(raw_steps, (list, tuple)):
        raise HarnessValidationError(
            "legacy step states must be an array",
            code="invalid_legacy_graph_state",
        )
    state_step_ids: list[str] = []
    for item in raw_steps:
        step = _mapping(item, "legacy_state.step_state")
        _exact_keys(
            step,
            {
                "step_id",
                "status",
                "attempts",
                "replans",
                "output_ref",
                "error",
                "metadata",
                "updated_at",
            },
            "legacy Step state",
        )
        step_id = required_text(step["step_id"], "legacy_state.step_id")
        HarnessStepStatus(step["status"])
        for counter_name in ("attempts", "replans"):
            counter = step[counter_name]
            if not isinstance(counter, int) or isinstance(counter, bool) or counter < 0:
                raise HarnessValidationError(
                    "legacy Step counters must be non-negative integers",
                    code="invalid_legacy_graph_state",
                )
        for field_name in ("output_ref", "error"):
            if step[field_name] is not None and not isinstance(step[field_name], str):
                raise HarnessValidationError(
                    f"legacy Step {field_name} must be text or null",
                    code="invalid_legacy_graph_state",
                )
        _mapping(step["metadata"], "legacy_state.step_metadata")
        if parse_datetime(step["updated_at"]) is None:
            raise HarnessValidationError(
                "legacy Step updated_at is required",
                code="invalid_legacy_graph_state",
            )
        state_step_ids.append(step_id)
    if len(state_step_ids) != len(set(state_step_ids)) or set(state_step_ids) != set(
        declared_step_ids
    ):
        raise HarnessValidationError(
            "legacy Step states do not match the declared workflow",
            code="invalid_legacy_graph_state",
        )
    current_step_id = value["current_step_id"]
    if current_step_id is not None and current_step_id not in state_step_ids:
        raise HarnessValidationError(
            "legacy current_step_id is outside the declared workflow",
            code="invalid_legacy_graph_state",
        )
    if parse_datetime(value["updated_at"]) is None:
        raise HarnessValidationError(
            "legacy state updated_at is required",
            code="invalid_legacy_graph_state",
        )


def _source_schema(value: Any) -> str:
    return str(value.get("schema_version")) if isinstance(value, Mapping) else "unknown"


def _quarantine_code(exc: Exception, *, fallback: str) -> str:
    if isinstance(exc, HarnessValidationError):
        code = str(exc.code)
        if code not in {"", "HarnessValidationError"}:
            return code
    return fallback


def _history_quarantine_code(exc: HarnessValidationError) -> str:
    code = str(exc.code)
    if code in {"", "HarnessValidationError"}:
        return "invalid_graph_history"
    if code in {
        "graph_history_evidence_missing",
        "graph_terminal_evidence_missing",
        "terminal_evidence_missing",
    }:
        return "graph_history_evidence_missing"
    if "schema" in code or "version" in code or "kernel" in code:
        return "unsupported_graph_history_version"
    if "mismatch" in code or "incompatible" in code:
        return "incompatible_graph_history"
    return code or "invalid_graph_history"


def _checksum(value: Any, field_name: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 71
        or not value.startswith("sha256:")
    ):
        raise HarnessValidationError(
            f"{field_name} must be a sha256 checksum",
            code="invalid_graph_checkpoint_checksum",
        )
    digest = value.removeprefix("sha256:")
    if any(character not in "0123456789abcdef" for character in digest):
        raise HarnessValidationError(
            f"{field_name} must be a lowercase sha256 checksum",
            code="invalid_graph_checkpoint_checksum",
        )
    return value


def _optional_checksum(value: Any, field_name: str) -> str | None:
    return None if value is None else _checksum(value, field_name)


def _positive_int(value: Any, field_name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise HarnessValidationError(
            f"{field_name} must be a positive integer",
            code="invalid_graph_replay_sequence",
        )
    return value


def _datetime(value: Any, field_name: str) -> datetime:
    if not isinstance(value, datetime):
        raise HarnessValidationError(
            f"{field_name} must be a datetime", code="invalid_graph_checkpoint_datetime"
        )
    try:
        return ensure_utc(value)
    except (TypeError, ValueError) as exc:
        raise HarnessValidationError(
            f"{field_name} must be timezone-aware",
            code="invalid_graph_checkpoint_datetime",
        ) from exc


__all__ = [
    "DecisionVerifier",
    "HARNESS_LEGACY_EVENT_EVIDENCE_SCHEMA",
    "HarnessGraphCheckpoint",
    "HarnessGraphCheckpointReadResult",
    "HarnessGraphCheckpointReader",
    "HarnessGraphCheckpointStore",
    "HarnessGraphDecisionInputSnapshot",
    "HarnessGraphHistoryReducer",
    "HarnessGraphReplayReport",
    "HarnessGraphReplayReadResult",
    "HarnessGraphStateReadResult",
    "HarnessGraphStateReader",
    "HarnessLegacyEventCategory",
    "HarnessLegacyEventEvidence",
    "HarnessLegacyEventReadResult",
    "HarnessLegacyEventReader",
    "HarnessPinnedDecisionKernel",
    "InMemoryHarnessGraphCheckpointStore",
    "graph_history_evidence_ref",
    "quarantine_graph_replay_failure",
]
