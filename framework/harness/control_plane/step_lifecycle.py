from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from framework.harness.control_plane.errors import HarnessValidationError
from framework.harness.control_plane.cumulative_budget import (
    HarnessCumulativeBudgetFact,
)
from framework.harness.control_plane.gate_registry import GateReference
from framework.harness.control_plane.gates import HarnessGateResult
from framework.harness.control_plane.graph_state import (
    HarnessAttemptEvidenceReference,
    HarnessEvidenceKind,
    HarnessNodeInstanceState,
)
from framework.harness.control_plane.policy import HarnessBudgetSnapshot
from framework.harness.control_plane.state import HarnessStepState, HarnessStepStatus
from framework.harness.quality.verdict import HarnessQualityVerdict
from framework.harness.workflow.canonical import (
    canonical_checksum,
    freeze_json,
    optional_text,
    required_text,
    thaw_json,
)
from framework.harness.workflow.graph import (
    HarnessContractKind,
    HarnessContractReference,
)
from framework.harness.workflow.step import HarnessStepSpec
from framework.harness.workflow.versioning import HARNESS_STEP_LIFECYCLE_VERSION
from framework.harness.workers.result import HarnessWorkerResult, HarnessWorkerStatus


_CHECKSUM_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")


class StepLifecycleBindingMode(StrEnum):
    LEGACY_UNBOUND = "legacy_unbound"
    GRAPH_BOUND = "graph_bound"


class StepLifecycleTransitionType(StrEnum):
    PLAN_STEP = "plan_step"
    EXECUTE_STEP = "execute_step"
    VERIFY_STEP = "verify_step"
    COMPLETE_STEP = "complete_step"
    RETRY_STEP = "retry_step"
    REPLAN_STEP = "replan_step"
    ROUTE_TO_REPAIR = "route_to_repair"
    WAIT_FOR_APPROVAL = "wait_for_approval"
    BLOCK_STEP = "block_step"
    FAIL_STEP = "fail_step"
    HALT_STEP = "halt_step"


@dataclass(frozen=True, slots=True)
class StepLifecycleState:
    step_id: str
    status: HarnessStepStatus | str
    attempts: int = 0
    replans: int = 0
    error: str | None = None
    binding_mode: StepLifecycleBindingMode | str = (
        StepLifecycleBindingMode.LEGACY_UNBOUND
    )
    step_ref: HarnessContractReference | None = None
    node_instance_id: str | None = None
    last_event_sequence: int | None = None
    evidence_refs: tuple[HarnessAttemptEvidenceReference, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "step_id",
            required_text(self.step_id, "step_lifecycle_state.step_id"),
        )
        object.__setattr__(self, "status", HarnessStepStatus(self.status))
        _nonnegative_int(self.attempts, "step_lifecycle_state.attempts")
        _nonnegative_int(self.replans, "step_lifecycle_state.replans")
        binding_mode = StepLifecycleBindingMode(self.binding_mode)
        object.__setattr__(
            self,
            "error",
            optional_text(self.error, "step_lifecycle_state.error"),
        )
        step_ref = self.step_ref
        node_instance_id = optional_text(
            self.node_instance_id,
            "step_lifecycle_state.node_instance_id",
        )
        last_event_sequence = self.last_event_sequence
        raw_evidence_refs = tuple(self.evidence_refs)
        if not all(
            isinstance(item, HarnessAttemptEvidenceReference)
            for item in raw_evidence_refs
        ):
            raise TypeError(
                "evidence_refs must contain HarnessAttemptEvidenceReference values"
            )
        evidence_refs = tuple(
            sorted(
                raw_evidence_refs,
                key=lambda item: (
                    item.event_sequence,
                    item.kind.value,
                    item.evidence_ref,
                ),
            )
        )
        if len(evidence_refs) != len(set(evidence_refs)):
            raise HarnessValidationError(
                "Step lifecycle evidence references must be unique",
                code="duplicate_step_lifecycle_evidence",
            )
        if binding_mode is StepLifecycleBindingMode.LEGACY_UNBOUND:
            if (
                step_ref is not None
                or node_instance_id is not None
                or last_event_sequence is not None
                or evidence_refs
            ):
                raise HarnessValidationError(
                    "Legacy Step lifecycle state cannot carry graph identity",
                    code="ambiguous_step_lifecycle_binding",
                )
        else:
            if not isinstance(step_ref, HarnessContractReference):
                raise HarnessValidationError(
                    "Graph-bound Step lifecycle state requires exact step_ref",
                    code="missing_step_lifecycle_identity",
                )
            if step_ref.contract_kind is not HarnessContractKind.STEP:
                raise HarnessValidationError(
                    "Graph-bound step_ref must reference a Step contract",
                    code="step_lifecycle_identity_mismatch",
                )
            if not _step_reference_matches_id(step_ref, self.step_id):
                raise HarnessValidationError(
                    "Graph-bound step_ref does not match step_id",
                    code="step_lifecycle_identity_mismatch",
                )
            if node_instance_id is None or last_event_sequence is None:
                raise HarnessValidationError(
                    "Graph-bound Step lifecycle state requires node and sequence identity",
                    code="missing_step_lifecycle_identity",
                )
            _nonnegative_int(
                last_event_sequence,
                "step_lifecycle_state.last_event_sequence",
            )
            if (
                self.status
                in {
                    HarnessStepStatus.RUNNING,
                    HarnessStepStatus.VERIFYING,
                    HarnessStepStatus.RETRYING,
                }
                and self.attempts < 1
            ):
                raise HarnessValidationError(
                    "Active graph-bound Step phase requires a positive attempt",
                    code="invalid_step_lifecycle_attempt_state",
                )
            for evidence in evidence_refs:
                _validate_evidence_binding(
                    evidence,
                    node_instance_id=node_instance_id,
                    attempt=self.attempts,
                    last_event_sequence=last_event_sequence,
                )
        object.__setattr__(self, "binding_mode", binding_mode)
        object.__setattr__(self, "step_ref", step_ref)
        object.__setattr__(self, "node_instance_id", node_instance_id)
        object.__setattr__(self, "last_event_sequence", last_event_sequence)
        object.__setattr__(self, "evidence_refs", evidence_refs)

    @classmethod
    def from_legacy(cls, state: HarnessStepState) -> StepLifecycleState:
        if not isinstance(state, HarnessStepState):
            raise TypeError("state must be HarnessStepState")
        return cls(
            step_id=state.step_id,
            status=state.status,
            attempts=state.attempts,
            replans=state.replans,
            error=state.error,
            binding_mode=StepLifecycleBindingMode.LEGACY_UNBOUND,
        )

    @classmethod
    def from_node_instance(
        cls,
        state: HarnessNodeInstanceState,
    ) -> StepLifecycleState:
        if not isinstance(state, HarnessNodeInstanceState):
            raise TypeError("state must be HarnessNodeInstanceState")
        if state.step_id is None or state.step_status is None:
            raise HarnessValidationError(
                "Step lifecycle requires an executable node instance",
                code="invalid_step_lifecycle_node_instance",
            )
        return cls(
            step_id=state.step_id,
            status=state.step_status,
            attempts=state.attempt,
            replans=state.replans,
            error=state.terminal_reason or state.error_code,
            binding_mode=StepLifecycleBindingMode.GRAPH_BOUND,
            step_ref=state.step_ref,
            node_instance_id=state.instance_id,
            last_event_sequence=state.last_event_sequence,
            evidence_refs=tuple(
                item for item in state.evidence_refs if item.attempt == state.attempt
            ),
        )

    @property
    def attempt(self) -> int:
        return self.attempts

    def to_dict(self) -> dict[str, Any]:
        return {
            "step_id": self.step_id,
            "status": self.status.value,
            "attempt": self.attempts,
            "replans": self.replans,
            "error": self.error,
            "binding_mode": self.binding_mode.value,
            "step_ref": None if self.step_ref is None else self.step_ref.to_dict(),
            "node_instance_id": self.node_instance_id,
            "last_event_sequence": self.last_event_sequence,
            "evidence_refs": [item.to_dict() for item in self.evidence_refs],
        }


@dataclass(frozen=True, slots=True)
class StepLifecycleBudget:
    max_turns: int
    turns_used: int
    max_replans: int
    replans_used: int
    max_retries_per_step: int
    max_worker_calls: int
    worker_calls_used: int
    halt_on_budget_exceeded: bool = True

    def __post_init__(self) -> None:
        _positive_int(self.max_turns, "step_lifecycle_budget.max_turns")
        _nonnegative_int(self.turns_used, "step_lifecycle_budget.turns_used")
        _nonnegative_int(self.max_replans, "step_lifecycle_budget.max_replans")
        _nonnegative_int(self.replans_used, "step_lifecycle_budget.replans_used")
        _nonnegative_int(
            self.max_retries_per_step,
            "step_lifecycle_budget.max_retries_per_step",
        )
        _positive_int(
            self.max_worker_calls,
            "step_lifecycle_budget.max_worker_calls",
        )
        _nonnegative_int(
            self.worker_calls_used,
            "step_lifecycle_budget.worker_calls_used",
        )
        if not isinstance(self.halt_on_budget_exceeded, bool):
            raise HarnessValidationError(
                "step_lifecycle_budget.halt_on_budget_exceeded must be boolean",
                code="invalid_step_lifecycle_budget",
            )

    @classmethod
    def from_snapshot(cls, snapshot: HarnessBudgetSnapshot) -> StepLifecycleBudget:
        if not isinstance(snapshot, HarnessBudgetSnapshot):
            raise TypeError("snapshot must be HarnessBudgetSnapshot")
        return cls(
            max_turns=snapshot.max_turns,
            turns_used=snapshot.turns_used,
            max_replans=snapshot.max_replans,
            replans_used=snapshot.replans_used,
            max_retries_per_step=snapshot.max_retries_per_step,
            max_worker_calls=snapshot.max_worker_calls,
            worker_calls_used=snapshot.worker_calls_used,
            halt_on_budget_exceeded=snapshot.halt_on_budget_exceeded,
        )

    def to_dict(self) -> dict[str, int | bool]:
        return {
            "max_turns": self.max_turns,
            "turns_used": self.turns_used,
            "max_replans": self.max_replans,
            "replans_used": self.replans_used,
            "max_retries_per_step": self.max_retries_per_step,
            "max_worker_calls": self.max_worker_calls,
            "worker_calls_used": self.worker_calls_used,
            "halt_on_budget_exceeded": self.halt_on_budget_exceeded,
        }


@dataclass(frozen=True, slots=True)
class StepWorkerObservation:
    status: HarnessWorkerStatus | str
    error: str | None = None
    error_type: str | None = None
    candidate_observations: Mapping[str, Any] = field(default_factory=dict)
    accepted_evidence: HarnessAttemptEvidenceReference | None = None
    cumulative_budget_fact: HarnessCumulativeBudgetFact | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "status", HarnessWorkerStatus(self.status))
        object.__setattr__(
            self,
            "error",
            optional_text(self.error, "step_worker_observation.error"),
        )
        object.__setattr__(
            self,
            "error_type",
            optional_text(
                self.error_type,
                "step_worker_observation.error_type",
            ),
        )
        observations = freeze_json(
            self.candidate_observations,
            "step_worker_observation.candidate_observations",
        )
        if not isinstance(observations, Mapping):
            raise HarnessValidationError(
                "worker candidate observations must be an object",
                code="invalid_step_lifecycle_observation",
            )
        object.__setattr__(self, "candidate_observations", observations)
        if self.accepted_evidence is not None:
            _require_evidence_kind(
                self.accepted_evidence,
                HarnessEvidenceKind.ACTIVITY_RESULT,
                "worker observation",
            )
        if self.cumulative_budget_fact is not None and not isinstance(
            self.cumulative_budget_fact,
            HarnessCumulativeBudgetFact,
        ):
            raise TypeError(
                "cumulative_budget_fact must be HarnessCumulativeBudgetFact"
            )

    @classmethod
    def from_worker_result(
        cls,
        result: HarnessWorkerResult,
        *,
        accepted_evidence: HarnessAttemptEvidenceReference | None = None,
        cumulative_budget_fact: HarnessCumulativeBudgetFact | None = None,
    ) -> StepWorkerObservation:
        if not isinstance(result, HarnessWorkerResult):
            raise TypeError("result must be HarnessWorkerResult")
        diagnostics = (
            result.diagnostics if isinstance(result.diagnostics, Mapping) else {}
        )
        error_type = diagnostics.get("error_type")
        if error_type is None:
            error_type = result.output.get("error_type")
        return cls(
            status=result.status,
            error=result.error,
            error_type=None if error_type is None else str(error_type),
            candidate_observations=result.candidate_payload(),
            accepted_evidence=accepted_evidence,
            cumulative_budget_fact=cumulative_budget_fact,
        )

    def control_payload(self) -> dict[str, Any]:
        return {
            "status": self.status.value,
            "error": self.error,
            "error_type": self.error_type,
            "cumulative_budget_fact": (
                None
                if self.cumulative_budget_fact is None
                else self.cumulative_budget_fact.control_projection()
            ),
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            **self.control_payload(),
            "candidate_observations": thaw_json(self.candidate_observations),
            "accepted_evidence": _evidence_dict(self.accepted_evidence),
        }


@dataclass(frozen=True, slots=True)
class StepGateObservation:
    gate_name: str
    passed: bool
    reason: str | None = None
    details: Mapping[str, Any] = field(default_factory=dict)
    gate_reference: str | None = None
    input_ref: str | None = None
    result_ref: str | None = None
    gate_reason_code: str | None = None
    accepted_evidence: HarnessAttemptEvidenceReference | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "gate_name",
            required_text(self.gate_name, "step_gate_observation.gate_name"),
        )
        if not isinstance(self.passed, bool):
            raise HarnessValidationError(
                "step_gate_observation.passed must be boolean",
                code="invalid_step_lifecycle_observation",
            )
        object.__setattr__(
            self,
            "reason",
            optional_text(self.reason, "step_gate_observation.reason"),
        )
        details = freeze_json(self.details, "step_gate_observation.details")
        if not isinstance(details, Mapping):
            raise HarnessValidationError(
                "Gate observation details must be an object",
                code="invalid_step_lifecycle_observation",
            )
        object.__setattr__(self, "details", details)
        harness_gate = details.get("harness_gate")
        harness_gate = harness_gate if isinstance(harness_gate, Mapping) else {}
        reference = _coalesce_exact_value(
            self.gate_reference,
            harness_gate.get("reference"),
            "step_gate_observation.gate_reference",
        )
        input_ref = _coalesce_exact_value(
            self.input_ref,
            harness_gate.get("input_ref"),
            "step_gate_observation.input_ref",
        )
        result_ref = _coalesce_exact_value(
            self.result_ref,
            harness_gate.get("result_ref"),
            "step_gate_observation.result_ref",
        )
        gate_reason_code = _coalesce_exact_value(
            self.gate_reason_code,
            harness_gate.get("reason_code"),
            "step_gate_observation.gate_reason_code",
        )
        evidence_values = (reference, input_ref, result_ref, gate_reason_code)
        if reference is not None:
            parsed_reference = GateReference.parse(reference)
            if parsed_reference.gate_id != self.gate_name:
                raise HarnessValidationError(
                    "Gate observation reference does not match gate_name",
                    code="step_gate_identity_mismatch",
                )
        has_durable_evidence = bool(harness_gate) or any(
            value is not None for value in evidence_values[1:]
        )
        if self.accepted_evidence is not None:
            has_durable_evidence = True
        if has_durable_evidence:
            if not all(value is not None for value in evidence_values):
                raise HarnessValidationError(
                    "Gate observation evidence is incomplete",
                    code="incomplete_step_gate_evidence",
                )
            input_ref = _checksum(input_ref, "step_gate_observation.input_ref")
            result_ref = _checksum(result_ref, "step_gate_observation.result_ref")
        if self.accepted_evidence is not None:
            _require_evidence_kind(
                self.accepted_evidence,
                HarnessEvidenceKind.GATE_RESULT,
                "Gate observation",
            )
            if result_ref is not None and (
                self.accepted_evidence.evidence_ref != result_ref
            ):
                raise HarnessValidationError(
                    "Gate observation result_ref does not match durable evidence",
                    code="step_gate_evidence_mismatch",
                )
        object.__setattr__(self, "gate_reference", reference)
        object.__setattr__(self, "input_ref", input_ref)
        object.__setattr__(self, "result_ref", result_ref)
        object.__setattr__(self, "gate_reason_code", gate_reason_code)

    @property
    def identity(self) -> str:
        return self.gate_reference or self.gate_name

    @classmethod
    def from_gate_result(
        cls,
        result: HarnessGateResult,
        *,
        accepted_evidence: HarnessAttemptEvidenceReference | None = None,
    ) -> StepGateObservation:
        if not isinstance(result, HarnessGateResult):
            raise TypeError("result must be HarnessGateResult")
        harness_gate = result.details.get("harness_gate")
        reference = (
            harness_gate.get("reference") if isinstance(harness_gate, Mapping) else None
        )
        return cls(
            gate_name=result.gate_name,
            passed=result.passed,
            reason=result.reason,
            details=result.details,
            gate_reference=reference if isinstance(reference, str) else None,
            accepted_evidence=accepted_evidence,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "gate": self.gate_name,
            "passed": self.passed,
            "reason": self.reason,
            "details": thaw_json(self.details),
            "gate_reference": self.gate_reference,
            "input_ref": self.input_ref,
            "result_ref": self.result_ref,
            "reason_code": self.gate_reason_code,
            "accepted_evidence": _evidence_dict(self.accepted_evidence),
        }


@dataclass(frozen=True, slots=True)
class StepQualityObservation:
    passed: bool
    score: float | None = None
    issues: tuple[str, ...] = ()
    repair_hints: tuple[str, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)
    accepted_evidence: HarnessAttemptEvidenceReference | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.passed, bool):
            raise HarnessValidationError(
                "step_quality_observation.passed must be boolean",
                code="invalid_step_lifecycle_observation",
            )
        score = self.score
        if score is not None:
            if not isinstance(score, int | float) or isinstance(score, bool):
                raise HarnessValidationError(
                    "step_quality_observation.score must be numeric",
                    code="invalid_step_lifecycle_observation",
                )
            score = float(score)
            if not 0 <= score <= 1:
                raise HarnessValidationError(
                    "step_quality_observation.score must be between zero and one",
                    code="invalid_step_lifecycle_observation",
                )
        if not isinstance(self.issues, list | tuple):
            raise HarnessValidationError(
                "step_quality_observation.issues must be a sequence",
                code="invalid_step_lifecycle_observation",
            )
        if not isinstance(self.repair_hints, list | tuple):
            raise HarnessValidationError(
                "step_quality_observation.repair_hints must be a sequence",
                code="invalid_step_lifecycle_observation",
            )
        metadata = freeze_json(self.metadata, "step_quality_observation.metadata")
        if not isinstance(metadata, Mapping):
            raise HarnessValidationError(
                "quality observation metadata must be an object",
                code="invalid_step_lifecycle_observation",
            )
        object.__setattr__(self, "score", score)
        object.__setattr__(self, "issues", tuple(str(item) for item in self.issues))
        object.__setattr__(
            self,
            "repair_hints",
            tuple(str(item) for item in self.repair_hints),
        )
        object.__setattr__(self, "metadata", metadata)
        if self.accepted_evidence is not None:
            _require_evidence_kind(
                self.accepted_evidence,
                HarnessEvidenceKind.GATE_RESULT,
                "quality observation",
            )

    @classmethod
    def from_verdict(
        cls,
        verdict: HarnessQualityVerdict,
        *,
        accepted_evidence: HarnessAttemptEvidenceReference | None = None,
    ) -> StepQualityObservation:
        if not isinstance(verdict, HarnessQualityVerdict):
            raise TypeError("verdict must be HarnessQualityVerdict")
        return cls(
            passed=verdict.passed,
            score=verdict.score,
            issues=verdict.issues,
            repair_hints=verdict.repair_hints,
            metadata=verdict.metadata,
            accepted_evidence=accepted_evidence,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "score": self.score,
            "issues": list(self.issues),
            "repair_hints": list(self.repair_hints),
            "metadata": thaw_json(self.metadata),
            "accepted_evidence": _evidence_dict(self.accepted_evidence),
        }


@dataclass(frozen=True, slots=True)
class StepLifecycleObservations:
    worker_result: StepWorkerObservation | None = None
    gate_results: tuple[StepGateObservation, ...] = ()
    quality_verdict: StepQualityObservation | None = None
    approval_granted: bool = False
    approval_evidence: HarnessAttemptEvidenceReference | None = None
    binding_mode: StepLifecycleBindingMode | str = (
        StepLifecycleBindingMode.LEGACY_UNBOUND
    )
    node_instance_id: str | None = None
    attempt: int | None = None
    last_event_sequence: int | None = None

    def __post_init__(self) -> None:
        if self.worker_result is not None and not isinstance(
            self.worker_result,
            StepWorkerObservation,
        ):
            raise TypeError("worker_result must be StepWorkerObservation")
        if self.quality_verdict is not None and not isinstance(
            self.quality_verdict,
            StepQualityObservation,
        ):
            raise TypeError("quality_verdict must be StepQualityObservation")
        if not isinstance(self.approval_granted, bool):
            raise HarnessValidationError(
                "approval_granted must be boolean",
                code="invalid_step_lifecycle_observation",
            )
        if self.approval_evidence is not None:
            _require_evidence_kind(
                self.approval_evidence,
                HarnessEvidenceKind.APPROVAL,
                "approval observation",
            )
        raw_gate_results = tuple(self.gate_results)
        if not all(isinstance(item, StepGateObservation) for item in raw_gate_results):
            raise TypeError("gate_results must contain StepGateObservation values")
        gate_results = tuple(
            sorted(
                raw_gate_results,
                key=lambda item: (
                    item.identity,
                    item.gate_name,
                    item.reason or "",
                ),
            )
        )
        identities = [item.identity for item in gate_results]
        if len(identities) != len(set(identities)):
            raise HarnessValidationError(
                "Gate observations must have unique exact identities",
                code="duplicate_step_gate_observation",
                details={"identities": sorted(set(identities))},
            )
        binding_mode = StepLifecycleBindingMode(self.binding_mode)
        node_instance_id = optional_text(
            self.node_instance_id,
            "step_lifecycle_observations.node_instance_id",
        )
        attempt = self.attempt
        last_event_sequence = self.last_event_sequence
        accepted_evidence = self._accepted_evidence_values(
            gate_results=gate_results,
        )
        if binding_mode is StepLifecycleBindingMode.LEGACY_UNBOUND:
            if (
                node_instance_id is not None
                or attempt is not None
                or last_event_sequence is not None
                or accepted_evidence
            ):
                raise HarnessValidationError(
                    "Legacy observations cannot carry graph-bound evidence",
                    code="ambiguous_step_lifecycle_binding",
                )
        else:
            if (
                node_instance_id is None
                or attempt is None
                or last_event_sequence is None
            ):
                raise HarnessValidationError(
                    "Graph-bound observations require node, attempt, and sequence identity",
                    code="missing_step_observation_identity",
                )
            _nonnegative_int(attempt, "step_lifecycle_observations.attempt")
            _nonnegative_int(
                last_event_sequence,
                "step_lifecycle_observations.last_event_sequence",
            )
            if self.worker_result is not None:
                _require_bound_observation(
                    self.worker_result.accepted_evidence,
                    label="worker",
                )
            for gate_result in gate_results:
                _require_bound_observation(
                    gate_result.accepted_evidence,
                    label="Gate",
                )
                _require_exact_gate_observation(gate_result)
            if self.quality_verdict is not None:
                _require_bound_observation(
                    self.quality_verdict.accepted_evidence,
                    label="quality",
                )
            if self.approval_granted:
                _require_bound_observation(
                    self.approval_evidence,
                    label="approval",
                )
            for evidence in accepted_evidence:
                _validate_evidence_binding(
                    evidence,
                    node_instance_id=node_instance_id,
                    attempt=attempt,
                    last_event_sequence=last_event_sequence,
                )
        object.__setattr__(self, "binding_mode", binding_mode)
        object.__setattr__(self, "node_instance_id", node_instance_id)
        object.__setattr__(self, "attempt", attempt)
        object.__setattr__(self, "last_event_sequence", last_event_sequence)
        object.__setattr__(self, "gate_results", gate_results)

    def _accepted_evidence_values(
        self,
        *,
        gate_results: tuple[StepGateObservation, ...] | None = None,
    ) -> tuple[HarnessAttemptEvidenceReference, ...]:
        resolved_gate_results = (
            tuple(self.gate_results) if gate_results is None else gate_results
        )
        candidates = (
            None
            if self.worker_result is None
            else self.worker_result.accepted_evidence,
            *(gate_result.accepted_evidence for gate_result in resolved_gate_results),
            None
            if self.quality_verdict is None
            else self.quality_verdict.accepted_evidence,
            self.approval_evidence,
        )
        unique: dict[
            tuple[str, str, str, int, int], HarnessAttemptEvidenceReference
        ] = {}
        for evidence in candidates:
            if evidence is None:
                continue
            key = (
                evidence.kind.value,
                evidence.evidence_ref,
                evidence.node_instance_id,
                evidence.attempt,
                evidence.event_sequence,
            )
            unique[key] = evidence
        return tuple(
            sorted(
                unique.values(),
                key=lambda item: (
                    item.event_sequence,
                    item.kind.value,
                    item.evidence_ref,
                ),
            )
        )

    @property
    def accepted_evidence(self) -> tuple[HarnessAttemptEvidenceReference, ...]:
        return self._accepted_evidence_values()

    @classmethod
    def from_legacy(
        cls,
        *,
        worker_result: HarnessWorkerResult | None = None,
        gate_results: tuple[HarnessGateResult, ...] = (),
        quality_verdict: HarnessQualityVerdict | None = None,
        approval_granted: bool = False,
    ) -> StepLifecycleObservations:
        return cls(
            worker_result=(
                None
                if worker_result is None
                else StepWorkerObservation.from_worker_result(worker_result)
            ),
            gate_results=tuple(
                StepGateObservation.from_gate_result(result) for result in gate_results
            ),
            quality_verdict=(
                None
                if quality_verdict is None
                else StepQualityObservation.from_verdict(quality_verdict)
            ),
            approval_granted=approval_granted,
            binding_mode=StepLifecycleBindingMode.LEGACY_UNBOUND,
        )

    @classmethod
    def for_node(
        cls,
        state: HarnessNodeInstanceState | StepLifecycleState,
        *,
        worker_result: StepWorkerObservation | None = None,
        gate_results: tuple[StepGateObservation, ...] = (),
        quality_verdict: StepQualityObservation | None = None,
        approval_granted: bool = False,
        approval_evidence: HarnessAttemptEvidenceReference | None = None,
    ) -> StepLifecycleObservations:
        lifecycle_state = (
            StepLifecycleState.from_node_instance(state)
            if isinstance(state, HarnessNodeInstanceState)
            else state
        )
        if not isinstance(lifecycle_state, StepLifecycleState):
            raise TypeError(
                "state must be HarnessNodeInstanceState or StepLifecycleState"
            )
        if lifecycle_state.binding_mode is not StepLifecycleBindingMode.GRAPH_BOUND:
            raise HarnessValidationError(
                "for_node requires graph-bound Step lifecycle state",
                code="step_lifecycle_binding_mode_mismatch",
            )
        return cls(
            worker_result=worker_result,
            gate_results=gate_results,
            quality_verdict=quality_verdict,
            approval_granted=approval_granted,
            approval_evidence=approval_evidence,
            binding_mode=StepLifecycleBindingMode.GRAPH_BOUND,
            node_instance_id=lifecycle_state.node_instance_id,
            attempt=lifecycle_state.attempt,
            last_event_sequence=lifecycle_state.last_event_sequence,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "binding_mode": self.binding_mode.value,
            "node_instance_id": self.node_instance_id,
            "attempt": self.attempt,
            "last_event_sequence": self.last_event_sequence,
            "worker_result": (
                None if self.worker_result is None else self.worker_result.to_dict()
            ),
            "gate_results": [result.to_dict() for result in self.gate_results],
            "quality_verdict": (
                None if self.quality_verdict is None else self.quality_verdict.to_dict()
            ),
            "approval_granted": self.approval_granted,
            "approval_evidence": _evidence_dict(self.approval_evidence),
        }

    def control_projection(self) -> dict[str, Any]:
        """Return only accepted fields that may influence lifecycle control."""

        return {
            "binding_mode": self.binding_mode.value,
            "node_instance_id": self.node_instance_id,
            "attempt": self.attempt,
            "last_event_sequence": self.last_event_sequence,
            "worker_result": (
                None
                if self.worker_result is None
                else {
                    **self.worker_result.control_payload(),
                    "accepted_evidence": _evidence_dict(
                        self.worker_result.accepted_evidence
                    ),
                }
            ),
            "gate_results": [result.to_dict() for result in self.gate_results],
            "quality_verdict": (
                None if self.quality_verdict is None else self.quality_verdict.to_dict()
            ),
            "approval_granted": self.approval_granted,
            "approval_evidence": _evidence_dict(self.approval_evidence),
        }

    @property
    def control_checksum(self) -> str:
        return canonical_checksum(self.control_projection())


@dataclass(frozen=True, slots=True)
class StepLifecycleTransition:
    transition_type: StepLifecycleTransitionType | str
    step_id: str
    reason_code: str
    target_step_id: str | None = None
    reason: str | None = None
    payload: Mapping[str, Any] = field(default_factory=dict)
    lifecycle_version: str = HARNESS_STEP_LIFECYCLE_VERSION
    binding_mode: StepLifecycleBindingMode | str = (
        StepLifecycleBindingMode.LEGACY_UNBOUND
    )
    step_ref: HarnessContractReference | None = None
    node_instance_id: str | None = None
    attempt: int | None = None
    last_event_sequence: int | None = None
    evidence_refs: tuple[HarnessAttemptEvidenceReference, ...] = ()

    def __post_init__(self) -> None:
        transition_type = StepLifecycleTransitionType(self.transition_type)
        step_id = required_text(self.step_id, "step_transition.step_id")
        reason_code = required_text(
            self.reason_code,
            "step_transition.reason_code",
        )
        target_step_id = optional_text(
            self.target_step_id,
            "step_transition.target_step_id",
        )
        if (
            transition_type is StepLifecycleTransitionType.ROUTE_TO_REPAIR
            and target_step_id is None
        ):
            raise HarnessValidationError(
                "repair transition requires target_step_id",
                code="invalid_step_lifecycle_transition",
            )
        if (
            transition_type is not StepLifecycleTransitionType.ROUTE_TO_REPAIR
            and target_step_id is not None
        ):
            raise HarnessValidationError(
                "only repair transition may carry target_step_id",
                code="invalid_step_lifecycle_transition",
            )
        payload = freeze_json(self.payload, "step_transition.payload")
        if not isinstance(payload, Mapping):
            raise HarnessValidationError(
                "step transition payload must be an object",
                code="invalid_step_lifecycle_transition",
            )
        lifecycle_version = required_text(
            self.lifecycle_version,
            "step_transition.lifecycle_version",
        )
        if lifecycle_version != HARNESS_STEP_LIFECYCLE_VERSION:
            raise HarnessValidationError(
                "Step transition requires the active lifecycle policy version",
                code="unsupported_step_lifecycle_version",
                details={"lifecycle_version": lifecycle_version},
            )
        binding_mode = StepLifecycleBindingMode(self.binding_mode)
        step_ref = self.step_ref
        node_instance_id = optional_text(
            self.node_instance_id,
            "step_transition.node_instance_id",
        )
        attempt = self.attempt
        last_event_sequence = self.last_event_sequence
        raw_evidence_refs = tuple(self.evidence_refs)
        if not all(
            isinstance(item, HarnessAttemptEvidenceReference)
            for item in raw_evidence_refs
        ):
            raise TypeError(
                "evidence_refs must contain HarnessAttemptEvidenceReference values"
            )
        evidence_refs = tuple(
            sorted(
                raw_evidence_refs,
                key=lambda item: (
                    item.event_sequence,
                    item.kind.value,
                    item.evidence_ref,
                ),
            )
        )
        if len(evidence_refs) != len(set(evidence_refs)):
            raise HarnessValidationError(
                "Step transition evidence references must be unique",
                code="duplicate_step_transition_evidence",
            )
        if binding_mode is StepLifecycleBindingMode.LEGACY_UNBOUND:
            if (
                step_ref is not None
                or node_instance_id is not None
                or attempt is not None
                or last_event_sequence is not None
                or evidence_refs
            ):
                raise HarnessValidationError(
                    "Legacy Step transition cannot carry graph identity",
                    code="ambiguous_step_lifecycle_binding",
                )
        else:
            if not isinstance(step_ref, HarnessContractReference):
                raise HarnessValidationError(
                    "Graph-bound transition requires exact step_ref",
                    code="missing_step_lifecycle_identity",
                )
            if (
                step_ref.contract_kind is not HarnessContractKind.STEP
                or not _step_reference_matches_id(step_ref, step_id)
            ):
                raise HarnessValidationError(
                    "Graph-bound transition step_ref does not match step_id",
                    code="step_lifecycle_identity_mismatch",
                )
            if (
                node_instance_id is None
                or attempt is None
                or last_event_sequence is None
            ):
                raise HarnessValidationError(
                    "Graph-bound transition requires node, attempt, and sequence identity",
                    code="missing_step_lifecycle_identity",
                )
            _nonnegative_int(attempt, "step_transition.attempt")
            _nonnegative_int(
                last_event_sequence,
                "step_transition.last_event_sequence",
            )
            for evidence in evidence_refs:
                _validate_evidence_binding(
                    evidence,
                    node_instance_id=node_instance_id,
                    attempt=attempt,
                    last_event_sequence=last_event_sequence,
                )
        object.__setattr__(self, "transition_type", transition_type)
        object.__setattr__(self, "step_id", step_id)
        object.__setattr__(self, "reason_code", reason_code)
        object.__setattr__(self, "target_step_id", target_step_id)
        object.__setattr__(
            self,
            "reason",
            optional_text(self.reason, "step_transition.reason"),
        )
        object.__setattr__(self, "payload", payload)
        object.__setattr__(self, "lifecycle_version", lifecycle_version)
        object.__setattr__(self, "binding_mode", binding_mode)
        object.__setattr__(self, "step_ref", step_ref)
        object.__setattr__(self, "node_instance_id", node_instance_id)
        object.__setattr__(self, "attempt", attempt)
        object.__setattr__(self, "last_event_sequence", last_event_sequence)
        object.__setattr__(self, "evidence_refs", evidence_refs)

    def to_dict(self) -> dict[str, Any]:
        return {
            "transition_type": self.transition_type.value,
            "step_id": self.step_id,
            "target_step_id": self.target_step_id,
            "reason_code": self.reason_code,
            "reason": self.reason,
            "payload": thaw_json(self.payload),
            "lifecycle_version": self.lifecycle_version,
            "binding_mode": self.binding_mode.value,
            "step_ref": None if self.step_ref is None else self.step_ref.to_dict(),
            "node_instance_id": self.node_instance_id,
            "attempt": self.attempt,
            "last_event_sequence": self.last_event_sequence,
            "evidence_refs": [item.to_dict() for item in self.evidence_refs],
        }


@dataclass(frozen=True, slots=True)
class _StepPolicySnapshot:
    retry_on_statuses: frozenset[str]
    fail_fast_error_types: frozenset[str]
    effective_max_attempts: int
    backoff_seconds: float
    worker_failure_repair_step_id: str | None
    verification_repair_step_id: str | None
    approval_required: bool
    declared_gate_reference: str | None

    @classmethod
    def from_step(cls, step: HarnessStepSpec) -> _StepPolicySnapshot:
        retry_policy = step.retry_policy
        metadata_repair = step.metadata.get("repair_step_id")
        metadata_repair_id = (
            None
            if metadata_repair is None or not str(metadata_repair).strip()
            else str(metadata_repair).strip()
        )
        return cls(
            retry_on_statuses=frozenset(retry_policy.retry_on_statuses),
            fail_fast_error_types=frozenset(retry_policy.fail_fast_error_types),
            effective_max_attempts=retry_policy.effective_max_attempts,
            backoff_seconds=retry_policy.backoff_seconds,
            worker_failure_repair_step_id=retry_policy.repair_step_id,
            verification_repair_step_id=(
                retry_policy.repair_step_id or metadata_repair_id
            ),
            approval_required=step.metadata.get("approval_required") is True,
            declared_gate_reference=step.quality_gate,
        )


class StepLifecycleStateMachine:
    __slots__ = ()
    version = HARNESS_STEP_LIFECYCLE_VERSION

    def next_transition(
        self,
        step: HarnessStepSpec,
        state: StepLifecycleState | HarnessNodeInstanceState,
        observations: StepLifecycleObservations,
        budget: StepLifecycleBudget | HarnessBudgetSnapshot,
    ) -> StepLifecycleTransition | None:
        if not isinstance(step, HarnessStepSpec):
            raise TypeError("step must be HarnessStepSpec")
        if isinstance(state, HarnessNodeInstanceState):
            state = StepLifecycleState.from_node_instance(state)
        elif not isinstance(state, StepLifecycleState):
            raise TypeError(
                "state must be StepLifecycleState or HarnessNodeInstanceState"
            )
        if not isinstance(observations, StepLifecycleObservations):
            raise TypeError("observations must be StepLifecycleObservations")
        if isinstance(budget, HarnessBudgetSnapshot):
            budget = StepLifecycleBudget.from_snapshot(budget)
        elif not isinstance(budget, StepLifecycleBudget):
            raise TypeError(
                "budget must be StepLifecycleBudget or HarnessBudgetSnapshot"
            )
        if step.step_id != state.step_id:
            raise HarnessValidationError(
                "Step lifecycle state belongs to another Step definition",
                code="step_lifecycle_identity_mismatch",
                details={"step_id": step.step_id, "state_step_id": state.step_id},
            )
        _validate_state_observation_binding(state, observations)

        policy = _StepPolicySnapshot.from_step(step)
        status = state.status
        if status is HarnessStepStatus.PENDING:
            return self._plan_or_halt(state, budget)
        if status is HarnessStepStatus.PLANNING:
            return self._after_plan(state, observations, budget)
        if status is HarnessStepStatus.PLAN_VERIFIED:
            return self._execute_or_halt(state, budget)
        if status is HarnessStepStatus.RUNNING:
            return self._after_execute(
                state,
                observations,
                budget,
                policy,
            )
        if status is HarnessStepStatus.RETRYING:
            return self._execute_or_halt(
                state,
                budget,
                reason="retry current step",
                reason_code="retry_execution_requested",
            )
        if status is HarnessStepStatus.VERIFYING:
            return self._after_verify(
                state,
                observations,
                budget,
                policy,
            )
        if status is HarnessStepStatus.REPLANNING:
            return self._plan_or_halt(
                state,
                budget,
                reason="controlled replan",
                reason_code="controlled_replan",
            )
        if status in {HarnessStepStatus.SUCCEEDED, HarnessStepStatus.SKIPPED}:
            return None
        if status is HarnessStepStatus.WAITING_APPROVAL:
            if observations.binding_mode is StepLifecycleBindingMode.GRAPH_BOUND:
                if observations.approval_evidence is None:
                    return None
                if not observations.approval_granted:
                    return None
                exhausted = _turn_budget_transition(
                    state,
                    budget,
                    observations=observations,
                )
                if exhausted is not None:
                    return exhausted
                return _transition(
                    StepLifecycleTransitionType.VERIFY_STEP,
                    state,
                    "approval_granted_verify",
                    reason="Harness approval granted",
                    observations=observations,
                )
            return _transition(
                StepLifecycleTransitionType.WAIT_FOR_APPROVAL,
                state,
                "step_waiting_for_approval",
                reason="step is waiting for approval",
            )
        if status is HarnessStepStatus.HALTED:
            return _transition(
                StepLifecycleTransitionType.HALT_STEP,
                state,
                "step_already_halted",
                reason=state.error or "step halted",
            )
        if status is HarnessStepStatus.FAILED:
            return _transition(
                StepLifecycleTransitionType.FAIL_STEP,
                state,
                "step_already_failed",
                reason=state.error or "step failed",
            )
        raise HarnessValidationError(
            "unsupported Step lifecycle status",
            code="unsupported_step_lifecycle_status",
            details={"status": status.value},
        )

    def _plan_or_halt(
        self,
        state: StepLifecycleState,
        budget: StepLifecycleBudget,
        *,
        reason: str | None = None,
        reason_code: str = "plan_requested",
    ) -> StepLifecycleTransition:
        exhausted = _turn_budget_transition(state, budget)
        if exhausted is not None:
            return exhausted
        return _transition(
            StepLifecycleTransitionType.PLAN_STEP,
            state,
            reason_code,
            reason=reason,
        )

    def _after_plan(
        self,
        state: StepLifecycleState,
        observations: StepLifecycleObservations,
        budget: StepLifecycleBudget,
    ) -> StepLifecycleTransition:
        gate_results = observations.gate_results
        if not gate_results or _all_gates_passed(gate_results):
            return self._execute_or_halt(
                state,
                budget,
                observations=observations,
            )
        payload = {
            "gate_results": [result.to_dict() for result in gate_results],
        }
        if _can_replan(state, budget):
            return _transition(
                StepLifecycleTransitionType.REPLAN_STEP,
                state,
                "plan_gate_failed_replan",
                reason="plan gate failed",
                payload=payload,
                observations=observations,
            )
        return _transition(
            StepLifecycleTransitionType.HALT_STEP,
            state,
            "plan_gate_failed_replans_exhausted",
            reason="plan gate failed and replan budget is exhausted",
            payload={**payload, "budget_exhausted": "replans"},
            observations=observations,
        )

    def _execute_or_halt(
        self,
        state: StepLifecycleState,
        budget: StepLifecycleBudget,
        *,
        observations: StepLifecycleObservations | None = None,
        reason: str | None = None,
        reason_code: str = "execution_requested",
    ) -> StepLifecycleTransition:
        exhausted = _turn_budget_transition(
            state,
            budget,
            observations=observations,
        )
        if exhausted is not None:
            return exhausted
        if budget.worker_calls_used >= budget.max_worker_calls:
            return _transition(
                StepLifecycleTransitionType.HALT_STEP,
                state,
                "worker_call_budget_exhausted",
                reason="worker call budget is exhausted",
                payload={"budget_exhausted": "worker_calls"},
                observations=observations,
            )
        return _transition(
            StepLifecycleTransitionType.EXECUTE_STEP,
            state,
            reason_code,
            reason=reason,
            observations=observations,
        )

    def _after_execute(
        self,
        state: StepLifecycleState,
        observations: StepLifecycleObservations,
        budget: StepLifecycleBudget,
        policy: _StepPolicySnapshot,
    ) -> StepLifecycleTransition:
        worker = observations.worker_result
        if worker is None:
            return _transition(
                StepLifecycleTransitionType.EXECUTE_STEP,
                state,
                "worker_result_pending",
                observations=observations,
            )
        cumulative_fact = worker.cumulative_budget_fact
        if cumulative_fact is not None:
            fact_payload = {
                "canonical_budget_fact": cumulative_fact.control_projection()
            }
            if cumulative_fact.resolution_status != "verified":
                return _transition(
                    StepLifecycleTransitionType.HALT_STEP,
                    state,
                    cumulative_fact.reason_code or "budget_fact_invalid",
                    reason="canonical cumulative LLM budget fact is invalid",
                    payload=fact_payload,
                    observations=observations,
                )
            if cumulative_fact.indeterminate:
                return _transition(
                    StepLifecycleTransitionType.HALT_STEP,
                    state,
                    "cumulative_llm_budget_indeterminate",
                    reason="cumulative LLM usage is indeterminate",
                    payload=fact_payload,
                    observations=observations,
                )
            if cumulative_fact.denied and budget.halt_on_budget_exceeded:
                return _transition(
                    StepLifecycleTransitionType.HALT_STEP,
                    state,
                    "cumulative_llm_budget_exhausted",
                    reason="cumulative LLM budget is exhausted",
                    payload=fact_payload,
                    observations=observations,
                )
        if worker.status is HarnessWorkerStatus.SUCCEEDED:
            if policy.approval_required and not observations.approval_granted:
                return _transition(
                    StepLifecycleTransitionType.WAIT_FOR_APPROVAL,
                    state,
                    "harness_approval_required",
                    reason="step requires Harness approval",
                    observations=observations,
                )
            exhausted = _turn_budget_transition(
                state,
                budget,
                observations=observations,
            )
            if exhausted is not None:
                return exhausted
            return _transition(
                StepLifecycleTransitionType.VERIFY_STEP,
                state,
                "worker_succeeded_verify",
                observations=observations,
            )
        if worker.status is HarnessWorkerStatus.WAITING_APPROVAL:
            if policy.approval_required and not observations.approval_granted:
                return _transition(
                    StepLifecycleTransitionType.WAIT_FOR_APPROVAL,
                    state,
                    "harness_approval_required",
                    reason="step requires Harness approval",
                    observations=observations,
                )
            return _transition(
                StepLifecycleTransitionType.HALT_STEP,
                state,
                "worker_approval_request_untrusted",
                reason="worker requested approval without Harness policy",
                observations=observations,
            )
        if worker.status is HarnessWorkerStatus.BLOCKED:
            return _transition(
                StepLifecycleTransitionType.BLOCK_STEP,
                state,
                "worker_blocked",
                reason=worker.error or "worker blocked",
                payload=worker.control_payload(),
                observations=observations,
            )
        if _can_retry(state, budget, policy, worker):
            return _transition(
                StepLifecycleTransitionType.RETRY_STEP,
                state,
                "worker_failure_retry",
                reason=worker.error or "worker failed with retryable status",
                payload={
                    "backoff_seconds": policy.backoff_seconds,
                    "worker_result": worker.control_payload(),
                },
                observations=observations,
            )
        if policy.worker_failure_repair_step_id is not None:
            return _transition(
                StepLifecycleTransitionType.ROUTE_TO_REPAIR,
                state,
                "worker_failure_repair",
                target_step_id=policy.worker_failure_repair_step_id,
                reason=worker.error or "worker failed; route to configured repair step",
                payload=worker.control_payload(),
                observations=observations,
            )
        return _transition(
            StepLifecycleTransitionType.FAIL_STEP,
            state,
            "worker_failure_terminal",
            reason=worker.error or "worker failed and retry budget is exhausted",
            payload=worker.control_payload(),
            observations=observations,
        )

    def _after_verify(
        self,
        state: StepLifecycleState,
        observations: StepLifecycleObservations,
        budget: StepLifecycleBudget,
        policy: _StepPolicySnapshot,
    ) -> StepLifecycleTransition:
        gate_results = observations.gate_results
        quality_verdict = observations.quality_verdict
        if state.binding_mode is StepLifecycleBindingMode.GRAPH_BOUND and (
            gate_results or quality_verdict is not None
        ):
            _require_declared_gate_observation(
                policy.declared_gate_reference,
                gate_results,
            )
        if not gate_results and quality_verdict is None:
            exhausted = _turn_budget_transition(
                state,
                budget,
                observations=observations,
            )
            if exhausted is not None:
                return exhausted
            return _transition(
                StepLifecycleTransitionType.VERIFY_STEP,
                state,
                "verification_requested",
                observations=observations,
            )

        verdict_failed = quality_verdict is not None and not quality_verdict.passed
        if gate_results and _all_gates_passed(gate_results) and not verdict_failed:
            return _transition(
                StepLifecycleTransitionType.COMPLETE_STEP,
                state,
                "verification_passed",
                observations=observations,
            )

        failed_results = [
            result.to_dict() for result in gate_results if not result.passed
        ]
        payload = {
            "gate_results": failed_results,
            "quality_verdict": (
                None if quality_verdict is None else quality_verdict.to_dict()
            ),
        }
        if policy.verification_repair_step_id is not None:
            return _transition(
                StepLifecycleTransitionType.ROUTE_TO_REPAIR,
                state,
                "verification_failed_repair",
                target_step_id=policy.verification_repair_step_id,
                reason="verification failed; route to repair step",
                payload=payload,
                observations=observations,
            )
        if _can_replan(state, budget):
            return _transition(
                StepLifecycleTransitionType.REPLAN_STEP,
                state,
                "verification_failed_replan",
                reason="verification failed",
                payload=payload,
                observations=observations,
            )
        return _transition(
            StepLifecycleTransitionType.HALT_STEP,
            state,
            "verification_failed_replans_exhausted",
            reason="verification failed and replan budget is exhausted",
            payload={**payload, "budget_exhausted": "replans"},
            observations=observations,
        )


def _transition(
    transition_type: StepLifecycleTransitionType,
    state: StepLifecycleState,
    reason_code: str,
    *,
    target_step_id: str | None = None,
    reason: str | None = None,
    payload: Mapping[str, Any] | None = None,
    observations: StepLifecycleObservations | None = None,
) -> StepLifecycleTransition:
    evidence_refs = () if observations is None else observations.accepted_evidence
    return StepLifecycleTransition(
        transition_type=transition_type,
        step_id=state.step_id,
        target_step_id=target_step_id,
        reason_code=reason_code,
        reason=reason,
        payload={} if payload is None else payload,
        binding_mode=state.binding_mode,
        step_ref=state.step_ref,
        node_instance_id=state.node_instance_id,
        attempt=(
            state.attempt
            if state.binding_mode is StepLifecycleBindingMode.GRAPH_BOUND
            else None
        ),
        last_event_sequence=state.last_event_sequence,
        evidence_refs=evidence_refs,
    )


def _turn_budget_transition(
    state: StepLifecycleState,
    budget: StepLifecycleBudget,
    *,
    observations: StepLifecycleObservations | None = None,
) -> StepLifecycleTransition | None:
    if budget.turns_used < budget.max_turns:
        return None
    return _transition(
        StepLifecycleTransitionType.HALT_STEP,
        state,
        "turn_budget_exhausted",
        reason="turn budget is exhausted",
        payload={
            "turn_count": budget.turns_used,
            "max_turns": budget.max_turns,
            "budget_exhausted": "turns",
        },
        observations=observations,
    )


def _all_gates_passed(results: tuple[StepGateObservation, ...]) -> bool:
    return all(result.passed for result in results)


def _can_replan(
    state: StepLifecycleState,
    budget: StepLifecycleBudget,
) -> bool:
    return (
        budget.replans_used < budget.max_replans and state.replans < budget.max_replans
    )


def _can_retry(
    state: StepLifecycleState,
    budget: StepLifecycleBudget,
    policy: _StepPolicySnapshot,
    worker: StepWorkerObservation,
) -> bool:
    if worker.status.value not in policy.retry_on_statuses:
        return False
    if (
        worker.error_type is not None
        and worker.error_type in policy.fail_fast_error_types
    ):
        return False
    budget_attempts = budget.max_retries_per_step + 1
    allowed_attempts = min(policy.effective_max_attempts, budget_attempts)
    return state.attempts < allowed_attempts


def _validate_state_observation_binding(
    state: StepLifecycleState,
    observations: StepLifecycleObservations,
) -> None:
    if state.binding_mode is not observations.binding_mode:
        raise HarnessValidationError(
            "Step lifecycle state and observations use different binding modes",
            code="step_lifecycle_binding_mode_mismatch",
        )
    if state.binding_mode is StepLifecycleBindingMode.LEGACY_UNBOUND:
        return
    if observations.node_instance_id != state.node_instance_id:
        raise HarnessValidationError(
            "Step observations belong to another node instance",
            code="cross_node_step_observation_rejected",
        )
    if observations.attempt != state.attempt:
        raise HarnessValidationError(
            "Step observations belong to another attempt",
            code="cross_attempt_step_observation_rejected",
        )
    if observations.last_event_sequence != state.last_event_sequence:
        raise HarnessValidationError(
            "Step observations were built from a stale graph projection",
            code="stale_step_observation_rejected",
            details={
                "state_last_event_sequence": state.last_event_sequence,
                "observation_last_event_sequence": observations.last_event_sequence,
            },
        )
    accepted_state_evidence = set(state.evidence_refs)
    for evidence in observations.accepted_evidence:
        if evidence not in accepted_state_evidence:
            raise HarnessValidationError(
                "Step observation evidence is not present in the accepted node projection",
                code="unaccepted_step_evidence_rejected",
                details={"evidence_ref": evidence.evidence_ref},
            )


def _validate_evidence_binding(
    evidence: HarnessAttemptEvidenceReference,
    *,
    node_instance_id: str,
    attempt: int,
    last_event_sequence: int,
) -> None:
    if evidence.node_instance_id != node_instance_id:
        raise HarnessValidationError(
            "Step evidence belongs to another node instance",
            code="cross_node_step_evidence_rejected",
        )
    if evidence.attempt != attempt:
        raise HarnessValidationError(
            "Step evidence belongs to another attempt",
            code="cross_attempt_step_evidence_rejected",
        )
    if evidence.event_sequence > last_event_sequence:
        raise HarnessValidationError(
            "Step evidence has not been accepted by the current projection",
            code="uncommitted_step_evidence_rejected",
        )


def _require_evidence_kind(
    evidence: HarnessAttemptEvidenceReference,
    expected_kind: HarnessEvidenceKind,
    label: str,
) -> None:
    if not isinstance(evidence, HarnessAttemptEvidenceReference):
        raise TypeError(f"{label} evidence must be HarnessAttemptEvidenceReference")
    if evidence.kind is not expected_kind:
        raise HarnessValidationError(
            f"{label} requires {expected_kind.value} evidence",
            code="step_observation_evidence_kind_mismatch",
        )


def _require_bound_observation(
    evidence: HarnessAttemptEvidenceReference | None,
    *,
    label: str,
) -> None:
    if evidence is None:
        raise HarnessValidationError(
            f"Graph-bound {label} observation requires durable evidence",
            code="missing_step_observation_evidence",
        )


def _require_exact_gate_observation(observation: StepGateObservation) -> None:
    if not all(
        (
            observation.gate_reference,
            observation.input_ref,
            observation.result_ref,
            observation.gate_reason_code,
        )
    ):
        raise HarnessValidationError(
            "Graph-bound Gate observation requires complete exact evidence",
            code="incomplete_step_gate_evidence",
        )
    GateReference.parse(observation.gate_reference)


def _require_declared_gate_observation(
    declared_reference: str | None,
    gate_results: tuple[StepGateObservation, ...],
) -> None:
    if declared_reference is None:
        return
    declared = GateReference.parse(declared_reference)
    observed = {
        GateReference.parse(result.gate_reference)
        for result in gate_results
        if result.gate_reference is not None
    }
    if declared not in observed:
        raise HarnessValidationError(
            "Graph-bound VERIFY is missing the exact declared Gate result",
            code="declared_step_gate_evidence_missing",
            details={"declared_gate": str(declared)},
        )


def _coalesce_exact_value(
    explicit: Any,
    embedded: Any,
    field_name: str,
) -> str | None:
    explicit_text = None if explicit is None else optional_text(explicit, field_name)
    embedded_text = None if embedded is None else optional_text(embedded, field_name)
    if (
        explicit_text is not None
        and embedded_text is not None
        and explicit_text != embedded_text
    ):
        raise HarnessValidationError(
            f"{field_name} conflicts with embedded Harness Gate evidence",
            code="step_gate_evidence_mismatch",
        )
    return explicit_text or embedded_text


def _checksum(value: Any, field_name: str) -> str:
    text = required_text(value, field_name)
    if _CHECKSUM_PATTERN.fullmatch(text) is None:
        raise HarnessValidationError(
            f"{field_name} must be a sha256 reference",
            code="invalid_step_observation_evidence",
        )
    return text


def _evidence_dict(
    evidence: HarnessAttemptEvidenceReference | None,
) -> dict[str, Any] | None:
    return None if evidence is None else evidence.to_dict()


def _step_reference_matches_id(
    reference: HarnessContractReference,
    step_id: str,
) -> bool:
    return reference.contract_id == step_id or reference.contract_id.endswith(
        f":{step_id}"
    )


def _nonnegative_int(value: Any, field_name: str) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise HarnessValidationError(
            f"{field_name} must be a non-negative integer",
            code="invalid_step_lifecycle_counter",
            details={"field": field_name},
        )


def _positive_int(value: Any, field_name: str) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise HarnessValidationError(
            f"{field_name} must be a positive integer",
            code="invalid_step_lifecycle_counter",
            details={"field": field_name},
        )


__all__ = (
    "StepGateObservation",
    "StepLifecycleBindingMode",
    "StepLifecycleBudget",
    "StepLifecycleObservations",
    "StepLifecycleState",
    "StepLifecycleStateMachine",
    "StepLifecycleTransition",
    "StepLifecycleTransitionType",
    "StepQualityObservation",
    "StepWorkerObservation",
)
