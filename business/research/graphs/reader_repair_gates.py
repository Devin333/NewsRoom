from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from pydantic import BaseModel, ValidationError

from framework.events.canonical import checksum_for
from framework.harness import (
    DeterministicGate,
    DeterministicGateRegistry,
    GateContext,
    GateReference,
    GateRegistration,
    HarnessGateResult,
)
from framework.harness.memory import MemoryWriteCandidate, MemoryWriteStatus

from business.research.domain import (
    READER_REPAIR_NAMESPACE,
    ReaderIssue,
    ReaderRepairCandidate,
    ReaderRepairCase,
    ReaderRepairContextPack,
    ReaderRepairResult,
    ReaderRepairSkillCandidateSeed,
    ReaderRepairStrategy,
    ReaderRepairVerificationCandidate,
    stable_research_id,
)


class ReaderRepairIssueGateAdapter(DeterministicGate):
    gate_name = "ReaderRepairIssueGate"
    gate_version = "1"

    def evaluate(self, context: GateContext) -> HarnessGateResult:
        issue, failure = _model_from_output(
            context,
            output_key="reader_issue",
            model_type=ReaderIssue,
            gate_name=self.gate_name,
        )
        if failure is not None:
            return failure
        assert isinstance(issue, ReaderIssue)
        violations = {}
        if not issue.source_refs:
            violations["source_refs"] = "required before memory recall"
        if not issue.payload_ref:
            violations["payload_ref"] = "required"
        return _result(self.gate_name, violations)


class ReaderRepairContextGateAdapter(DeterministicGate):
    gate_name = "ReaderRepairContextGate"
    gate_version = "1"

    def evaluate(self, context: GateContext) -> HarnessGateResult:
        pack, failure = _model_from_output(
            context,
            output_key="reader_repair_context_pack",
            model_type=ReaderRepairContextPack,
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
        assert isinstance(pack, ReaderRepairContextPack)
        assert isinstance(issue, ReaderIssue)
        unrelated = sorted(
            case.repair_case_id
            for case in pack.recalled_cases
            if case.issue.issue_type != pack.issue.issue_type
            and case.issue.error_signature != pack.issue.error_signature
        )
        violations: dict[str, Any] = {}
        if unrelated:
            violations["unrelated_case_refs"] = unrelated
        if (
            not pack.similar_failed_cases
            and not pack.failure_case_gap_report.get("no_failed_cases_available")
        ):
            violations["failed_case_evidence"] = "case or explicit gap required"
        if set(pack.source_refs) != set(pack.source_lineage.source_refs):
            violations["source_lineage"] = "context refs must match lineage"
        if pack.issue != issue:
            violations["issue"] = "context must preserve the verified issue"
        return _result(self.gate_name, violations)


class ReaderRepairCandidateGateAdapter(DeterministicGate):
    gate_name = "ReaderRepairCandidateGate"
    gate_version = "1"

    def evaluate(self, context: GateContext) -> HarnessGateResult:
        candidate, failure = _model_from_output(
            context,
            output_key="reader_repair_candidate",
            model_type=ReaderRepairCandidate,
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
        assert isinstance(candidate, ReaderRepairCandidate)
        assert isinstance(issue, ReaderIssue)
        assert isinstance(context_pack, ReaderRepairContextPack)
        outside_scope = sorted(set(candidate.target_region_refs) - set(issue.source_refs))
        violations: dict[str, Any] = (
            {"outside_target_region_refs": outside_scope} if outside_scope else {}
        )
        expected_bindings = _model_bindings(
            reader_repair_context_pack=context_pack,
        )
        if candidate.metadata.get("input_bindings") != expected_bindings:
            violations["input_bindings"] = "must match the verified repair context"
        return _result(self.gate_name, violations)


class ReaderRepairVerificationObservationGateAdapter(DeterministicGate):
    gate_name = "ReaderRepairVerificationObservationGate"
    gate_version = "1"

    def evaluate(self, context: GateContext) -> HarnessGateResult:
        observation, failure = _model_from_output(
            context,
            output_key="repair_verification_candidate",
            model_type=ReaderRepairVerificationCandidate,
            gate_name=self.gate_name,
        )
        if failure is not None:
            return failure
        candidate, failure = _prior_model(
            context,
            output_key="reader_repair_candidate",
            model_type=ReaderRepairCandidate,
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
        assert isinstance(observation, ReaderRepairVerificationCandidate)
        assert isinstance(candidate, ReaderRepairCandidate)
        assert isinstance(issue, ReaderIssue)
        observed_refs = set(observation.source_refs)
        for item in observation.observations:
            observed_refs.update(item.evidence_refs)
        violations: dict[str, Any] = {}
        if observation.candidate_id != candidate.candidate_id:
            violations["candidate_id"] = {
                "expected": candidate.candidate_id,
                "actual": observation.candidate_id,
            }
        expected_bindings = _model_bindings(
            reader_issue=issue,
            reader_repair_candidate=candidate,
        )
        if observation.metadata.get("input_bindings") != expected_bindings:
            violations["input_bindings"] = (
                "must match the verified issue and repair candidate"
            )
        outside_scope = sorted(observed_refs - set(issue.source_refs))
        if outside_scope:
            violations["outside_source_refs"] = outside_scope
        return _result(self.gate_name, violations)


class ReaderRepairResultGateAdapter(DeterministicGate):
    gate_name = "ReaderRepairResultGate"
    gate_version = "1"

    def evaluate(self, context: GateContext) -> HarnessGateResult:
        result, failure = _model_from_output(
            context,
            output_key="reader_repair_result",
            model_type=ReaderRepairResult,
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
            output_key="reader_repair_candidate",
            model_type=ReaderRepairCandidate,
            gate_name=self.gate_name,
        )
        if failure is not None:
            return failure
        verification, failure = _prior_model(
            context,
            output_key="repair_verification_candidate",
            model_type=ReaderRepairVerificationCandidate,
            gate_name=self.gate_name,
        )
        if failure is not None:
            return failure
        assert isinstance(result, ReaderRepairResult)
        assert isinstance(issue, ReaderIssue)
        assert isinstance(candidate, ReaderRepairCandidate)
        assert isinstance(verification, ReaderRepairVerificationCandidate)
        violations: dict[str, Any] = {}
        expected_attempt_id = stable_research_id(
            "repair_attempt",
            issue.issue_id,
            candidate.candidate_id,
        )
        expected_result_id = stable_research_id(
            "repair_result",
            expected_attempt_id,
        )
        expected_bindings = _model_bindings(
            reader_issue=issue,
            reader_repair_candidate=candidate,
            repair_verification_candidate=verification,
        )
        if result.attempt_id != expected_attempt_id:
            violations["attempt_id"] = "must bind the verified issue and candidate"
        if result.result_id != expected_result_id:
            violations["result_id"] = "must bind the deterministic repair attempt"
        if result.metadata.get("input_bindings") != expected_bindings:
            violations["input_bindings"] = "must match exact verified input checksums"
        if result.metadata.get("candidate_id") != candidate.candidate_id:
            violations["candidate_id"] = "must match the verified repair candidate"
        if result.metadata.get("repair_summary") != candidate.repair_summary:
            violations["repair_summary"] = "must match the verified repair candidate"
        if result.payload_before_ref != issue.payload_ref:
            violations["payload_before_ref"] = "must match the verified reader issue"
        if tuple(result.source_refs) != tuple(issue.source_refs):
            violations["source_refs"] = "must match the verified reader issue"
        verdicts: list[bool] = []
        for index, item in enumerate(result.verification_results):
            if (
                not isinstance(item, Mapping)
                or not isinstance(item.get("gate_name"), str)
                or not item["gate_name"].strip()
                or not isinstance(item.get("passed"), bool)
            ):
                violations[f"verification_results[{index}]"] = (
                    "deterministic gate_name and passed boolean required"
                )
                continue
            verdicts.append(bool(item["passed"]))
        if result.successful != all(verdicts):
            violations["successful"] = "must equal deterministic gate conjunction"
        if not result.successful and result.payload_after_ref is not None:
            violations["payload_after_ref"] = "failed repair must not expose a result"
        if result.successful and result.failure_reason is not None:
            violations["failure_reason"] = "successful repair must not claim failure"
        if not result.successful and not result.failure_reason:
            violations["failure_reason"] = "failed repair requires a reason"
        if result.metadata.get("skill_promotion_triggered") is not False:
            violations["skill_promotion_triggered"] = "must be explicitly false"
        return _result(self.gate_name, violations)


class ReaderRepairCaseGateAdapter(DeterministicGate):
    gate_name = "ReaderRepairCaseGate"
    gate_version = "1"

    def evaluate(self, context: GateContext) -> HarnessGateResult:
        case, failure = _model_from_output(
            context,
            output_key="reader_repair_case",
            model_type=ReaderRepairCase,
            gate_name=self.gate_name,
        )
        if failure is not None:
            return failure
        result, failure = _prior_model(
            context,
            output_key="reader_repair_result",
            model_type=ReaderRepairResult,
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
        assert isinstance(case, ReaderRepairCase)
        assert isinstance(result, ReaderRepairResult)
        assert isinstance(context_pack, ReaderRepairContextPack)
        violations: dict[str, Any] = {}
        expected_case_id = stable_research_id(
            "repair_case",
            context_pack.issue.issue_id,
            result.attempt_id,
        )
        expected_bindings = _model_bindings(
            reader_repair_context_pack=context_pack,
            reader_repair_result=result,
        )
        if case.repair_case_id != expected_case_id:
            violations["repair_case_id"] = "must bind the verified context and result"
        if case.metadata.get("input_bindings") != expected_bindings:
            violations["input_bindings"] = "must match exact verified input checksums"
        if case.issue != context_pack.issue:
            violations["issue"] = "case must preserve the verified context issue"
        if case.memory_kind != "episodic":
            violations["memory_kind"] = "ordinary repair must first record an episodic case"
        if case.repair_strategy != result.metadata.get("repair_summary"):
            violations["repair_strategy"] = "must match the verified repair candidate"
        if tuple(case.repair_attempt_refs) != (result.attempt_id,):
            violations["repair_attempt_refs"] = "must name only the verified attempt"
        if case.successful != result.successful:
            violations["successful"] = "case must match verified result"
        if case.payload_before_ref != result.payload_before_ref:
            violations["payload_before_ref"] = "case must match verified result"
        if case.payload_after_ref != result.payload_after_ref:
            violations["payload_after_ref"] = "case must match verified result"
        if case.verification_results != result.verification_results:
            violations["verification_results"] = "case must match verified result"
        if tuple(case.source_refs) != tuple(result.source_refs):
            violations["source_refs"] = "case must match verified result"
        if tuple(case.constraints) != tuple(context_pack.repair_constraints):
            violations["constraints"] = "case must match the verified context"
        if case.failure_reason != result.failure_reason:
            violations["failure_reason"] = "case must match verified result"
        if case.metadata.get("active_skill_mutation") is not False:
            violations["active_skill_mutation"] = "must be explicitly false"
        return _result(self.gate_name, violations)


class ReaderRepairStrategyBoundaryGateAdapter(DeterministicGate):
    gate_name = "ReaderRepairStrategyBoundaryGate"
    gate_version = "1"

    def evaluate(self, context: GateContext) -> HarnessGateResult:
        output, failure = _worker_output(context, gate_name=self.gate_name)
        if failure is not None:
            return failure
        assert output is not None
        bundle = output.get("strategy_candidate_bundle")
        if not isinstance(bundle, Mapping) or set(bundle) != {
            "input_bindings",
            "strategies",
            "skill_candidate_seeds",
        }:
            return _invalid(
                self.gate_name,
                "strategy_candidate_bundle must contain exact candidate arrays",
            )
        context_pack, failure = _prior_model(
            context,
            output_key="reader_repair_context_pack",
            model_type=ReaderRepairContextPack,
            gate_name=self.gate_name,
        )
        if failure is not None:
            return failure
        case, failure = _prior_model(
            context,
            output_key="reader_repair_case",
            model_type=ReaderRepairCase,
            gate_name=self.gate_name,
        )
        if failure is not None:
            return failure
        assert isinstance(context_pack, ReaderRepairContextPack)
        assert isinstance(case, ReaderRepairCase)
        try:
            strategies = tuple(
                ReaderRepairStrategy.model_validate(item)
                for item in _mapping_sequence(bundle["strategies"], "strategies")
            )
            seeds = tuple(
                ReaderRepairSkillCandidateSeed.model_validate(item)
                for item in _mapping_sequence(
                    bundle["skill_candidate_seeds"],
                    "skill_candidate_seeds",
                )
            )
        except (TypeError, ValueError, ValidationError) as exc:
            return _invalid(
                self.gate_name,
                "strategy candidate bundle is invalid",
                error_type=type(exc).__name__,
            )
        strategy_by_id = {strategy.strategy_id: strategy for strategy in strategies}
        strategy_ids = set(strategy_by_id)
        expected_bindings = _model_bindings(
            reader_repair_context_pack=context_pack,
            reader_repair_case=case,
        )
        allowed_case_ids = {
            case.repair_case_id,
            *(item.repair_case_id for item in context_pack.recalled_cases),
        }
        violations: dict[str, Any] = {}
        if bundle["input_bindings"] != expected_bindings:
            violations["input_bindings"] = "must match exact verified input checksums"
        duplicate_strategy_ids = sorted(
            strategy_id
            for strategy_id in strategy_ids
            if sum(item.strategy_id == strategy_id for item in strategies) > 1
        )
        if duplicate_strategy_ids:
            violations["duplicate_strategy_ids"] = duplicate_strategy_ids
        invalid_strategy_ids = sorted(
            strategy.strategy_id
            for strategy in strategies
            if strategy.issue_type != case.issue.issue_type
            or case.repair_case_id not in strategy.source_case_refs
            or not set(strategy.source_case_refs).issubset(allowed_case_ids)
            or strategy.status not in {"promoted_memory", "skill_candidate_ready"}
        )
        if invalid_strategy_ids:
            violations["invalid_strategy_ids"] = invalid_strategy_ids
        unbound_seeds = sorted(
            seed.seed_id for seed in seeds if seed.strategy.strategy_id not in strategy_ids
        )
        if unbound_seeds:
            violations["unbound_seed_ids"] = unbound_seeds
        unauthorized = sorted(
            seed.seed_id
            for seed in seeds
            if seed.publishes_skill
            or not seed.metadata.get("requires_harness_skill_evolution")
            or not seed.experience_refs
            or seed.strategy != strategy_by_id.get(seed.strategy.strategy_id)
            or set(seed.experience_refs)
            != {
                f"repair-case://{case_id}"
                for case_id in seed.strategy.source_case_refs
            }
            or seed.strategy.status
            not in {"promoted_memory", "skill_candidate_ready"}
        )
        if unauthorized:
            violations["unauthorized_seed_ids"] = unauthorized
        return _result(self.gate_name, violations)


class ReaderRepairMemoryPolicyGateAdapter(DeterministicGate):
    gate_name = "ReaderRepairMemoryPolicyGate"
    gate_version = "1"

    def evaluate(self, context: GateContext) -> HarnessGateResult:
        output, failure = _worker_output(context, gate_name=self.gate_name)
        if failure is not None:
            return failure
        assert output is not None
        payload = output.get("memory_write_candidate")
        if not isinstance(payload, Mapping) or set(payload) != {
            "candidate_id",
            "namespace",
            "content",
            "source_refs",
            "status",
            "metadata",
        }:
            return _invalid(
                self.gate_name,
                "memory_write_candidate fields are invalid",
            )
        try:
            candidate = MemoryWriteCandidate(
                candidate_id=payload["candidate_id"],
                namespace=payload["namespace"],
                content=dict(payload["content"]),
                source_refs=tuple(payload["source_refs"]),
                status=payload["status"],
                metadata=dict(payload["metadata"]),
            )
        except (TypeError, ValueError) as exc:
            return _invalid(
                self.gate_name,
                "memory_write_candidate is invalid",
                error_type=type(exc).__name__,
            )
        case, failure = _prior_model(
            context,
            output_key="reader_repair_case",
            model_type=ReaderRepairCase,
            gate_name=self.gate_name,
        )
        if failure is not None:
            return failure
        strategy_bundle, failure = _prior_mapping(
            context,
            output_key="strategy_candidate_bundle",
            gate_name=self.gate_name,
        )
        if failure is not None:
            return failure
        assert isinstance(case, ReaderRepairCase)
        assert strategy_bundle is not None
        violations: dict[str, Any] = {}
        expected_candidate_id = stable_research_id(
            "repair_memory_write",
            case.repair_case_id,
        )
        expected_bindings = {
            "reader_repair_case": checksum_for(case.to_dict()),
            "strategy_candidate_bundle": checksum_for(dict(strategy_bundle)),
        }
        if candidate.candidate_id != expected_candidate_id:
            violations["candidate_id"] = "must bind the verified repair case"
        if candidate.namespace != READER_REPAIR_NAMESPACE:
            violations["namespace"] = candidate.namespace
        if candidate.status is not MemoryWriteStatus.PROPOSED:
            violations["status"] = candidate.status.value
        if tuple(candidate.source_refs) != tuple(case.source_refs):
            violations["source_refs"] = "must match the verified repair case"
        if candidate.metadata.get("active_skill_mutation") is not False:
            violations["active_skill_mutation"] = "must be explicitly false"
        if candidate.metadata.get("input_bindings") != expected_bindings:
            violations["input_bindings"] = "must match exact verified input checksums"
        if set(candidate.content) != {
            "repair_case",
            "strategy_candidate_bundle",
        }:
            violations["content_fields"] = "must contain only verified memory inputs"
        raw_case = candidate.content.get("repair_case")
        if not isinstance(raw_case, Mapping):
            violations["repair_case"] = "required"
        else:
            try:
                candidate_case = ReaderRepairCase.model_validate(raw_case)
            except ValidationError:
                violations["repair_case"] = "invalid"
            else:
                if candidate_case != case:
                    violations["repair_case"] = "must match verified case"
        raw_strategy_bundle = candidate.content.get("strategy_candidate_bundle")
        if not isinstance(raw_strategy_bundle, Mapping):
            violations["strategy_candidate_bundle"] = "required"
        elif dict(raw_strategy_bundle) != dict(strategy_bundle):
            violations["strategy_candidate_bundle"] = (
                "must match the verified strategy candidate bundle"
            )
        forbidden = _nested_keys(
            (candidate.content, candidate.metadata)
        ).intersection(
            {
                "active_skill_package",
                "production_skill_version",
                "promote_skill",
                "publish",
                "publish_artifact",
            }
        )
        if forbidden:
            violations["skill_authority_fields"] = sorted(forbidden)
        return _result(self.gate_name, violations)


_READER_REPAIR_GATE_TYPES = (
    ReaderRepairIssueGateAdapter,
    ReaderRepairContextGateAdapter,
    ReaderRepairCandidateGateAdapter,
    ReaderRepairVerificationObservationGateAdapter,
    ReaderRepairResultGateAdapter,
    ReaderRepairCaseGateAdapter,
    ReaderRepairStrategyBoundaryGateAdapter,
    ReaderRepairMemoryPolicyGateAdapter,
)

READER_REPAIR_GATE_REFERENCES = tuple(
    f"{gate_type.gate_name}@{gate_type.gate_version}"
    for gate_type in _READER_REPAIR_GATE_TYPES
)


def build_reader_repair_gate_registry() -> DeterministicGateRegistry:
    gates = tuple(gate_type() for gate_type in _READER_REPAIR_GATE_TYPES)
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


def _worker_output(
    context: GateContext,
    *,
    gate_name: str,
) -> tuple[Mapping[str, Any] | None, HarnessGateResult | None]:
    worker_result = getattr(context, "worker_result", None)
    if worker_result is None or not isinstance(worker_result.output, Mapping):
        return None, _invalid(gate_name, "worker result is required")
    return worker_result.output, None


def _model_from_output(
    context: GateContext,
    *,
    output_key: str,
    model_type: type[BaseModel],
    gate_name: str,
) -> tuple[BaseModel | None, HarnessGateResult | None]:
    output, failure = _worker_output(context, gate_name=gate_name)
    if failure is not None:
        return None, failure
    assert output is not None
    payload = output.get(output_key)
    if not isinstance(payload, Mapping):
        return None, _invalid(
            gate_name,
            f"{output_key} must be an object",
            output_key=output_key,
        )
    try:
        return model_type.model_validate(payload), None
    except ValidationError as exc:
        return None, _invalid(
            gate_name,
            f"{output_key} does not match its domain contract",
            output_key=output_key,
            errors=[
                {
                    "path": ".".join(str(part) for part in item.get("loc", ())),
                    "type": str(item.get("type") or "validation_error"),
                }
                for item in exc.errors(include_url=False)
            ],
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
    try:
        return model_type.model_validate(payload), None
    except ValidationError as exc:
        return None, _invalid(
            gate_name,
            f"verified prior output {output_key} is invalid",
            output_key=output_key,
            error_type=type(exc).__name__,
        )


def _prior_mapping(
    context: GateContext,
    *,
    output_key: str,
    gate_name: str,
) -> tuple[Mapping[str, Any] | None, HarnessGateResult | None]:
    payload = _prior_payload(context, output_key)
    if not isinstance(payload, Mapping):
        return None, _invalid(
            gate_name,
            f"verified prior output {output_key} is required",
            output_key=output_key,
        )
    return payload, None


def _mapping_sequence(value: Any, field_name: str) -> tuple[Mapping[str, Any], ...]:
    if isinstance(value, str | bytes) or not isinstance(value, Sequence):
        raise TypeError(f"{field_name} must be an array")
    if not all(isinstance(item, Mapping) for item in value):
        raise TypeError(f"{field_name} must contain objects")
    return tuple(value)


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


def _nested_keys(value: Any) -> set[str]:
    keys: set[str] = set()
    pending = [value]
    while pending:
        current = pending.pop()
        if isinstance(current, Mapping):
            for key, item in current.items():
                keys.add(str(key).casefold())
                pending.append(item)
        elif isinstance(current, Sequence) and not isinstance(current, str | bytes):
            pending.extend(current)
    return keys


def _result(gate_name: str, violations: Mapping[str, Any]) -> HarnessGateResult:
    return HarnessGateResult(
        gate_name=gate_name,
        passed=not violations,
        reason=None if not violations else "reader repair contract validation failed",
        details={
            "reason_code": (
                "reader_repair_contract_passed"
                if not violations
                else "reader_repair_contract_failed"
            ),
            "violations": dict(violations),
        },
    )


def _invalid(gate_name: str, reason: str, **details: Any) -> HarnessGateResult:
    return HarnessGateResult(
        gate_name=gate_name,
        passed=False,
        reason=reason,
        details={"reason_code": "reader_repair_gate_input_invalid", **details},
    )


__all__ = [
    "READER_REPAIR_GATE_REFERENCES",
    "ReaderRepairCandidateGateAdapter",
    "ReaderRepairCaseGateAdapter",
    "ReaderRepairContextGateAdapter",
    "ReaderRepairIssueGateAdapter",
    "ReaderRepairMemoryPolicyGateAdapter",
    "ReaderRepairResultGateAdapter",
    "ReaderRepairStrategyBoundaryGateAdapter",
    "ReaderRepairVerificationObservationGateAdapter",
    "build_reader_repair_gate_registry",
]
