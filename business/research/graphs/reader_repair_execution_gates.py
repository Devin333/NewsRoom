from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from pydantic import BaseModel, ValidationError

from framework.events.canonical import checksum_for
from framework.harness import (
    HarnessCommittedNodeOutputReceipt,
    DeterministicGate,
    DeterministicGateRegistry,
    GateContext,
    GateReference,
    GateRegistration,
    HarnessGateResult,
    HarnessValidationError,
)

from business.research.domain import (
    ReaderIssue,
    ReaderRepairApplicationCandidate,
    ReaderRepairApplicationObservationCandidate,
    ReaderRepairApplicationVerificationRecord,
    ReaderRepairContextPack,
    ReaderRepairPatchCandidate,
    ReaderRepairResult,
    ResearchReaderPayload,
)
from business.research.graphs.reader_repair_contracts import (
    READER_REPAIR_COMMITTED_OUTPUT_RECEIPT_KEY,
    READER_REPAIR_RESULT_OUTPUT_KEY,
)
from business.research.graphs.reader_repair_execution_workers import (
    build_reader_repair_committed_result,
)
from business.research.reader_repair.application import (
    ReaderRepairApplicationError,
    apply_reader_repair_candidate,
    verify_reader_repair_application,
)


class ReaderRepairPatchCandidateGateAdapter(DeterministicGate):
    gate_name = "ReaderRepairPatchCandidateGate"
    gate_version = "1"

    def evaluate(self, context: GateContext) -> HarnessGateResult:
        candidate, failure = _model_from_output(
            context,
            output_key="reader_repair_patch_candidate",
            model_type=ReaderRepairPatchCandidate,
            gate_name=self.gate_name,
        )
        if failure is not None:
            return failure
        payload, failure = _run_input_model(
            context,
            input_key="reader_payload",
            model_type=ResearchReaderPayload,
            gate_name=self.gate_name,
        )
        if failure is not None:
            return failure
        issue, failure = _prior_model(
            context,
            output_key="reader_issue",
            model_type=ReaderIssue,
            gate_name=self.gate_name,
        )
        if failure is not None:
            return failure
        context_pack, failure = _prior_model(
            context,
            output_key="reader_repair_context_pack",
            model_type=ReaderRepairContextPack,
            gate_name=self.gate_name,
        )
        if failure is not None:
            return failure
        assert isinstance(candidate, ReaderRepairPatchCandidate)
        assert isinstance(payload, ResearchReaderPayload)
        assert isinstance(issue, ReaderIssue)
        assert isinstance(context_pack, ReaderRepairContextPack)

        expected_bindings = _model_bindings(
            reader_payload=payload,
            reader_repair_context_pack=context_pack,
        )
        violations: dict[str, Any] = {}
        if candidate.metadata.get("input_bindings") != expected_bindings:
            violations["input_bindings"] = (
                "must match the root payload and verified repair context"
            )
        if context_pack.issue != issue:
            violations["issue"] = "repair context issue is not bound"
        if issue.payload_ref != payload.payload_id:
            violations["payload_ref"] = "issue does not identify the root payload"
        if issue.paper_id != payload.paper.paper_id:
            violations["paper_id"] = "issue does not identify the root paper"
        outside_scope = sorted(
            set(candidate.target_region_refs) - set(issue.source_refs)
        )
        if outside_scope:
            violations["outside_target_region_refs"] = outside_scope
        try:
            apply_reader_repair_candidate(payload=payload, candidate=candidate)
        except ReaderRepairApplicationError as exc:
            violations["application"] = {
                "code": exc.code,
                "details": exc.details,
            }
        return _result(self.gate_name, violations)


class ReaderRepairApplicationCandidateGateAdapter(DeterministicGate):
    gate_name = "ReaderRepairApplicationCandidateGate"
    gate_version = "1"

    def evaluate(self, context: GateContext) -> HarnessGateResult:
        application, failure = _model_from_output(
            context,
            output_key="reader_repair_application_candidate",
            model_type=ReaderRepairApplicationCandidate,
            gate_name=self.gate_name,
        )
        if failure is not None:
            return failure
        payload, failure = _run_input_model(
            context,
            input_key="reader_payload",
            model_type=ResearchReaderPayload,
            gate_name=self.gate_name,
        )
        if failure is not None:
            return failure
        candidate, failure = _prior_model(
            context,
            output_key="reader_repair_patch_candidate",
            model_type=ReaderRepairPatchCandidate,
            gate_name=self.gate_name,
        )
        if failure is not None:
            return failure
        assert isinstance(application, ReaderRepairApplicationCandidate)
        assert isinstance(payload, ResearchReaderPayload)
        assert isinstance(candidate, ReaderRepairPatchCandidate)

        violations: dict[str, Any] = {}
        try:
            expected = apply_reader_repair_candidate(
                payload=payload,
                candidate=candidate,
            )
        except ReaderRepairApplicationError as exc:
            violations["application"] = {
                "code": exc.code,
                "details": exc.details,
            }
        else:
            if application != expected:
                violations["application_candidate"] = (
                    "must equal the deterministic in-memory application"
                )
        return _result(self.gate_name, violations)


class ReaderRepairApplicationObservationGateAdapter(DeterministicGate):
    gate_name = "ReaderRepairApplicationObservationGate"
    gate_version = "1"

    def evaluate(self, context: GateContext) -> HarnessGateResult:
        observation, failure = _model_from_output(
            context,
            output_key="reader_repair_application_observation",
            model_type=ReaderRepairApplicationObservationCandidate,
            gate_name=self.gate_name,
        )
        if failure is not None:
            return failure
        issue, failure = _prior_model(
            context,
            output_key="reader_issue",
            model_type=ReaderIssue,
            gate_name=self.gate_name,
        )
        if failure is not None:
            return failure
        candidate, failure = _prior_model(
            context,
            output_key="reader_repair_patch_candidate",
            model_type=ReaderRepairPatchCandidate,
            gate_name=self.gate_name,
        )
        if failure is not None:
            return failure
        application, failure = _prior_model(
            context,
            output_key="reader_repair_application_candidate",
            model_type=ReaderRepairApplicationCandidate,
            gate_name=self.gate_name,
        )
        if failure is not None:
            return failure
        assert isinstance(observation, ReaderRepairApplicationObservationCandidate)
        assert isinstance(issue, ReaderIssue)
        assert isinstance(candidate, ReaderRepairPatchCandidate)
        assert isinstance(application, ReaderRepairApplicationCandidate)

        observed_refs = {
            *observation.source_refs,
            *(
                ref
                for item in observation.observations
                for ref in item.evidence_refs
            ),
        }
        expected_bindings = {
            "reader_repair_patch_candidate": checksum_for(candidate.to_dict()),
            "reader_repair_application_candidate": checksum_for(
                application.to_dict()
            ),
        }
        violations: dict[str, Any] = {}
        if observation.candidate_id != candidate.candidate_id:
            violations["candidate_id"] = "must match the verified patch candidate"
        if observation.application_id != application.application_id:
            violations["application_id"] = (
                "must match the deterministic application candidate"
            )
        if observation.input_bindings != expected_bindings:
            violations["input_bindings"] = (
                "must match the patch and application candidate checksums"
            )
        if set(observation.source_refs) != set(application.source_refs):
            violations["source_refs"] = (
                "must match the deterministic application source refs"
            )
        outside_scope = sorted(observed_refs - set(issue.source_refs))
        if outside_scope:
            violations["outside_source_refs"] = outside_scope
        return _result(self.gate_name, violations)


class ReaderRepairApplicationVerificationGateAdapter(DeterministicGate):
    gate_name = "ReaderRepairApplicationVerificationGate"
    gate_version = "1"

    def evaluate(self, context: GateContext) -> HarnessGateResult:
        record, failure = _model_from_output(
            context,
            output_key="reader_repair_application_verification",
            model_type=ReaderRepairApplicationVerificationRecord,
            gate_name=self.gate_name,
        )
        if failure is not None:
            return failure
        payload, failure = _run_input_model(
            context,
            input_key="reader_payload",
            model_type=ResearchReaderPayload,
            gate_name=self.gate_name,
        )
        if failure is not None:
            return failure
        issue, failure = _prior_model(
            context,
            output_key="reader_issue",
            model_type=ReaderIssue,
            gate_name=self.gate_name,
        )
        if failure is not None:
            return failure
        candidate, failure = _prior_model(
            context,
            output_key="reader_repair_patch_candidate",
            model_type=ReaderRepairPatchCandidate,
            gate_name=self.gate_name,
        )
        if failure is not None:
            return failure
        application, failure = _prior_model(
            context,
            output_key="reader_repair_application_candidate",
            model_type=ReaderRepairApplicationCandidate,
            gate_name=self.gate_name,
        )
        if failure is not None:
            return failure
        observation, failure = _prior_model(
            context,
            output_key="reader_repair_application_observation",
            model_type=ReaderRepairApplicationObservationCandidate,
            gate_name=self.gate_name,
        )
        if failure is not None:
            return failure
        assert isinstance(record, ReaderRepairApplicationVerificationRecord)
        assert isinstance(payload, ResearchReaderPayload)
        assert isinstance(issue, ReaderIssue)
        assert isinstance(candidate, ReaderRepairPatchCandidate)
        assert isinstance(application, ReaderRepairApplicationCandidate)
        assert isinstance(observation, ReaderRepairApplicationObservationCandidate)

        expected = verify_reader_repair_application(
            payload=payload,
            issue=issue,
            candidate=candidate,
            application=application,
            observation=observation,
        )
        violations: dict[str, Any] = {}
        if record != expected:
            violations["verification_record"] = (
                "must equal the deterministic application verification record"
            )
        failed_checks = [item.check_id for item in expected.checks if not item.passed]
        if failed_checks:
            violations["failed_checks"] = failed_checks
        return _result(self.gate_name, violations)


class ReaderRepairCommittedResultGateAdapter(DeterministicGate):
    gate_name = "ReaderRepairCommittedResultGate"
    gate_version = "1"

    def __init__(self, *, graph_definition_checksum: str) -> None:
        self._graph_definition_checksum = str(graph_definition_checksum)

    def evaluate(self, context: GateContext) -> HarnessGateResult:
        output = getattr(getattr(context, "worker_result", None), "output", None)
        expected_output_keys = {
            READER_REPAIR_RESULT_OUTPUT_KEY,
            READER_REPAIR_COMMITTED_OUTPUT_RECEIPT_KEY,
        }
        if not isinstance(output, Mapping) or set(output) != expected_output_keys:
            return _invalid(
                self.gate_name,
                "committed repair result worker output fields are invalid",
                expected_output_keys=sorted(expected_output_keys),
            )
        result, failure = _model_from_output(
            context,
            output_key=READER_REPAIR_RESULT_OUTPUT_KEY,
            model_type=ReaderRepairResult,
            gate_name=self.gate_name,
        )
        if failure is not None:
            return failure
        raw_receipt = output[READER_REPAIR_COMMITTED_OUTPUT_RECEIPT_KEY]
        if not isinstance(raw_receipt, Mapping):
            return _invalid(
                self.gate_name,
                "committed node-output receipt must be an object",
            )
        try:
            receipt = HarnessCommittedNodeOutputReceipt.from_dict(raw_receipt)
        except (HarnessValidationError, TypeError, ValueError) as exc:
            return _invalid(
                self.gate_name,
                "committed node-output receipt is invalid",
                error_code=getattr(exc, "code", type(exc).__name__),
            )
        payload, failure = _run_input_model(
            context,
            input_key="reader_payload",
            model_type=ResearchReaderPayload,
            gate_name=self.gate_name,
        )
        if failure is not None:
            return failure
        issue, failure = _prior_model(
            context,
            output_key="reader_issue",
            model_type=ReaderIssue,
            gate_name=self.gate_name,
        )
        if failure is not None:
            return failure
        candidate, failure = _prior_model(
            context,
            output_key="reader_repair_patch_candidate",
            model_type=ReaderRepairPatchCandidate,
            gate_name=self.gate_name,
        )
        if failure is not None:
            return failure
        application, failure = _prior_model(
            context,
            output_key="reader_repair_application_candidate",
            model_type=ReaderRepairApplicationCandidate,
            gate_name=self.gate_name,
        )
        if failure is not None:
            return failure
        observation, failure = _prior_model(
            context,
            output_key="reader_repair_application_observation",
            model_type=ReaderRepairApplicationObservationCandidate,
            gate_name=self.gate_name,
        )
        if failure is not None:
            return failure
        verification, failure = _prior_model(
            context,
            output_key="reader_repair_application_verification",
            model_type=ReaderRepairApplicationVerificationRecord,
            gate_name=self.gate_name,
        )
        if failure is not None:
            return failure
        assert isinstance(result, ReaderRepairResult)
        assert isinstance(payload, ResearchReaderPayload)
        assert isinstance(issue, ReaderIssue)
        assert isinstance(candidate, ReaderRepairPatchCandidate)
        assert isinstance(application, ReaderRepairApplicationCandidate)
        assert isinstance(observation, ReaderRepairApplicationObservationCandidate)
        assert isinstance(verification, ReaderRepairApplicationVerificationRecord)
        try:
            expected = build_reader_repair_committed_result(
                payload=payload,
                issue=issue,
                candidate=candidate,
                application=application,
                observation=observation,
                verification=verification,
                receipt=receipt,
                graph_definition_checksum=self._graph_definition_checksum,
            )
        except HarnessValidationError as exc:
            return _result(
                self.gate_name,
                {
                    "committed_result": {
                        "code": exc.code,
                        "details": exc.details,
                    }
                },
            )
        violations: dict[str, Any] = {}
        if result != expected:
            violations["reader_repair_result"] = (
                "must equal the deterministic committed repair result"
            )
        return _result(self.gate_name, violations)


_READER_REPAIR_EXECUTION_GATE_TYPES = (
    ReaderRepairPatchCandidateGateAdapter,
    ReaderRepairApplicationCandidateGateAdapter,
    ReaderRepairApplicationObservationGateAdapter,
    ReaderRepairApplicationVerificationGateAdapter,
    ReaderRepairCommittedResultGateAdapter,
)

READER_REPAIR_EXECUTION_GATE_REFERENCES = tuple(
    f"{gate_type.gate_name}@{gate_type.gate_version}"
    for gate_type in _READER_REPAIR_EXECUTION_GATE_TYPES
)


def build_reader_repair_execution_gate_registry(
    *,
    graph_definition_checksum: str | None = None,
) -> DeterministicGateRegistry:
    if graph_definition_checksum is None:
        from business.research.graphs.reader_repair import (
            build_reader_repair_graph_definition,
        )

        graph_definition_checksum = (
            build_reader_repair_graph_definition().definition_checksum
        )
    if graph_definition_checksum is None:  # pragma: no cover - model invariant
        raise AssertionError("Reader Repair Graph checksum was not materialized")
    gates = (
        ReaderRepairPatchCandidateGateAdapter(),
        ReaderRepairApplicationCandidateGateAdapter(),
        ReaderRepairApplicationObservationGateAdapter(),
        ReaderRepairApplicationVerificationGateAdapter(),
        ReaderRepairCommittedResultGateAdapter(
            graph_definition_checksum=graph_definition_checksum,
        ),
    )
    return DeterministicGateRegistry(
        GateRegistration(
            reference=GateReference(
                gate_id=gate.gate_name,
                version=gate.gate_version,
            ),
            gate=gate,
        )
        for gate in gates
    )


def _model_from_output(
    context: GateContext,
    *,
    output_key: str,
    model_type: type[BaseModel],
    gate_name: str,
) -> tuple[BaseModel | None, HarnessGateResult | None]:
    worker_result = getattr(context, "worker_result", None)
    output = getattr(worker_result, "output", None)
    payload = output.get(output_key) if isinstance(output, Mapping) else None
    if not isinstance(payload, Mapping):
        return None, _invalid(
            gate_name,
            f"{output_key} must be an object",
            output_key=output_key,
        )
    return _validate_model(
        payload,
        model_type=model_type,
        gate_name=gate_name,
        field_name=output_key,
    )


def _prior_model(
    context: GateContext,
    *,
    output_key: str,
    model_type: type[BaseModel],
    gate_name: str,
) -> tuple[BaseModel | None, HarnessGateResult | None]:
    payload = _prior_payload(context, output_key)
    if not isinstance(payload, Mapping):
        return None, _invalid(
            gate_name,
            f"verified prior output {output_key} is required",
            output_key=output_key,
        )
    return _validate_model(
        payload,
        model_type=model_type,
        gate_name=gate_name,
        field_name=output_key,
    )


def _run_input_model(
    context: GateContext,
    *,
    input_key: str,
    model_type: type[BaseModel],
    gate_name: str,
) -> tuple[BaseModel | None, HarnessGateResult | None]:
    state = _context_state(context)
    run_spec = getattr(context, "run_spec", None)
    if run_spec is None:
        run_spec = getattr(state, "run_spec", None)
    inputs = getattr(run_spec, "inputs", None)
    payload = inputs.get(input_key) if isinstance(inputs, Mapping) else None
    if isinstance(payload, BaseModel):
        payload = payload.model_dump(mode="json", exclude_none=True)
    if not isinstance(payload, Mapping):
        return None, _invalid(
            gate_name,
            f"root input {input_key} is required",
            input_key=input_key,
        )
    return _validate_model(
        payload,
        model_type=model_type,
        gate_name=gate_name,
        field_name=input_key,
    )


def _validate_model(
    payload: Mapping[str, Any],
    *,
    model_type: type[BaseModel],
    gate_name: str,
    field_name: str,
) -> tuple[BaseModel | None, HarnessGateResult | None]:
    try:
        return model_type.model_validate(payload), None
    except ValidationError as exc:
        return None, _invalid(
            gate_name,
            f"{field_name} does not match its domain contract",
            field_name=field_name,
            errors=[
                {
                    "path": ".".join(str(part) for part in item.get("loc", ())),
                    "type": str(item.get("type") or "validation_error"),
                }
                for item in exc.errors(include_url=False)
            ],
        )


def _model_bindings(**values: BaseModel) -> dict[str, str]:
    return {
        key: checksum_for(value.model_dump(mode="json", exclude_none=True))
        for key, value in values.items()
    }


def _context_state(context: GateContext) -> Any:
    """Use the canonical Harness state while keeping small test fakes valid."""

    graph_state = getattr(context, "graph_state", None)
    return graph_state if graph_state is not None else getattr(context, "state", None)


def _prior_payload(context: GateContext, output_key: str) -> Any:
    outputs = getattr(context, "outputs", None)
    if isinstance(outputs, Mapping) and output_key in outputs:
        return _single_output_value(outputs[output_key], output_key)
    state = _context_state(context)
    metadata = getattr(state, "metadata", None)
    state_outputs = metadata.get("outputs") if isinstance(metadata, Mapping) else None
    record = state_outputs.get(output_key) if isinstance(state_outputs, Mapping) else None
    return (
        _single_output_value(record, output_key)
        if isinstance(record, Mapping)
        else None
    )


def _single_output_value(value: Any, output_key: str) -> Any:
    """Read a Graph single-output slot without assuming one wire shape."""

    if isinstance(value, Mapping) and output_key in value:
        return value[output_key]
    return value


def _result(gate_name: str, violations: Mapping[str, Any]) -> HarnessGateResult:
    return HarnessGateResult(
        gate_name=gate_name,
        passed=not violations,
        reason=None if not violations else "reader repair execution contract failed",
        details={
            "reason_code": (
                "reader_repair_execution_contract_passed"
                if not violations
                else "reader_repair_execution_contract_failed"
            ),
            "violations": dict(violations),
        },
    )


def _invalid(gate_name: str, reason: str, **details: Any) -> HarnessGateResult:
    return HarnessGateResult(
        gate_name=gate_name,
        passed=False,
        reason=reason,
        details={
            "reason_code": "reader_repair_execution_gate_input_invalid",
            **details,
        },
    )


__all__ = [
    "READER_REPAIR_EXECUTION_GATE_REFERENCES",
    "ReaderRepairApplicationCandidateGateAdapter",
    "ReaderRepairApplicationObservationGateAdapter",
    "ReaderRepairApplicationVerificationGateAdapter",
    "ReaderRepairCommittedResultGateAdapter",
    "ReaderRepairPatchCandidateGateAdapter",
    "build_reader_repair_execution_gate_registry",
]
