from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from framework.events.canonical import checksum_for
from framework.harness.control_plane.cumulative_budget import (
    HarnessCumulativeBudgetFact,
)
from framework.harness.control_plane.errors import HarnessValidationError
from framework.harness.control_plane.policy import HarnessBudgetSnapshot
from framework.harness.control_plane.state import HarnessState, HarnessStepState
from framework.harness.quality.verdict import HarnessQualityVerdict
from framework.harness.workflow.step import HarnessStepSpec, HarnessWorkerType
from framework.harness.workers.result import HarnessWorkerResult


@dataclass(frozen=True)
class HarnessGateResult:
    gate_name: str
    passed: bool
    reason: str | None = None
    details: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not str(self.gate_name).strip():
            raise HarnessValidationError("gate_name is required")
        if not isinstance(self.passed, bool):
            raise HarnessValidationError("gate result passed must be a boolean")
        object.__setattr__(self, "gate_name", str(self.gate_name).strip())
        object.__setattr__(self, "details", dict(self.details))

    def with_evidence(
        self,
        *,
        gate_reference: str,
        input_ref: str,
        reason_code: str,
    ) -> "HarnessGateResult":
        reference = str(gate_reference).strip()
        if not reference or "@" not in reference:
            raise HarnessValidationError("gate_reference must include an exact version")
        if not _is_checksum(input_ref):
            raise HarnessValidationError("input_ref must be a sha256 reference")
        code = str(reason_code).strip()
        if not code:
            raise HarnessValidationError("reason_code is required")
        raw_result = self.to_dict()
        details = dict(self.details)
        details["harness_gate"] = {
            "reference": reference,
            "input_ref": input_ref,
            "result_ref": checksum_for(raw_result),
            "reason_code": code,
        }
        return HarnessGateResult(
            gate_name=self.gate_name,
            passed=self.passed,
            reason=self.reason,
            details=details,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "gate": self.gate_name,
            "passed": self.passed,
            "reason": self.reason,
            "details": self.details,
        }


@dataclass(frozen=True)
class GateContext:
    state: HarnessState
    step_spec: HarnessStepSpec
    step_state: HarnessStepState
    worker_result: HarnessWorkerResult | None = None
    quality_verdict: HarnessQualityVerdict | None = None
    budget: HarnessBudgetSnapshot | None = None
    cumulative_budget_fact: HarnessCumulativeBudgetFact | None = None


class DeterministicGate:
    gate_name = "deterministic"
    gate_version = "1"
    gate_dependencies: tuple[str, ...] = ()

    def evaluate(self, context: GateContext) -> HarnessGateResult:
        raise NotImplementedError


class ToolAllowlistGate(DeterministicGate):
    gate_name = "tool_allowlist"

    def evaluate(self, context: GateContext) -> HarnessGateResult:
        requested_tools = _coerce_string_set(context.step_spec.metadata.get("requested_tools", ()))
        if context.worker_result is not None:
            requested_tools |= _coerce_string_set(_worker_diagnostics(context.worker_result).get("requested_tools", ()))
        allowlist = _coerce_string_set(context.step_spec.metadata.get("tool_allowlist", ()))
        denied = sorted(requested_tools - allowlist)
        if denied:
            return HarnessGateResult(
                gate_name=self.gate_name,
                passed=False,
                reason="worker requested tools outside step allowlist",
                details={"denied": denied, "allowlist": sorted(allowlist)},
            )
        return HarnessGateResult(
            gate_name=self.gate_name,
            passed=True,
            details={"requested_tools": sorted(requested_tools), "allowlist": sorted(allowlist)},
        )


class OutputSchemaGate(DeterministicGate):
    gate_name = "output_schema"

    def evaluate(self, context: GateContext) -> HarnessGateResult:
        schema = context.step_spec.metadata.get("output_schema")
        if schema is None:
            return HarnessGateResult(gate_name=self.gate_name, passed=True, reason="no output schema configured")
        if not isinstance(schema, dict):
            raise HarnessValidationError("output_schema metadata must be a dict")
        if context.worker_result is None:
            return HarnessGateResult(gate_name=self.gate_name, passed=False, reason="worker result is required")
        output = context.worker_result.output
        missing = sorted(str(field) for field in schema.get("required", ()) if field not in output)
        invalid_types: list[str] = []
        properties = schema.get("properties", {})
        if properties and not isinstance(properties, dict):
            raise HarnessValidationError("output_schema.properties must be a dict")
        for name, definition in properties.items():
            if name not in output or not isinstance(definition, dict):
                continue
            expected_type = definition.get("type")
            if expected_type and not _matches_json_type(output[name], str(expected_type)):
                invalid_types.append(str(name))
        passed = not missing and not invalid_types
        return HarnessGateResult(
            gate_name=self.gate_name,
            passed=passed,
            reason=None if passed else "worker output does not match step schema",
            details={"missing": missing, "invalid_types": invalid_types},
        )


class DeduplicationGate(DeterministicGate):
    gate_name = "deduplication"

    def evaluate(self, context: GateContext) -> HarnessGateResult:
        known_plan_keys = set(_coerce_string_set(context.state.metadata.get("plan_keys", ())))
        plan_key = context.step_spec.metadata.get("plan_key")
        if context.worker_result is not None:
            plan_key = context.worker_result.output.get("plan_key", plan_key)
        if plan_key and str(plan_key) in known_plan_keys:
            return HarnessGateResult(
                gate_name=self.gate_name,
                passed=False,
                reason="duplicate plan key",
                details={"plan_key": str(plan_key)},
            )

        seen_claims = set(_coerce_string_set(context.state.metadata.get("claims", ())))
        claims = _coerce_string_set(_result_sequence(context.worker_result, "claims"))
        duplicate_claims = sorted(seen_claims.intersection(claims))
        if duplicate_claims:
            return HarnessGateResult(
                gate_name=self.gate_name,
                passed=False,
                reason="duplicate claims",
                details={"claims": duplicate_claims},
            )

        seen_questions = set(_coerce_string_set(context.state.metadata.get("questions", ())))
        questions = _coerce_string_set(_result_sequence(context.worker_result, "questions"))
        duplicate_questions = sorted(seen_questions.intersection(questions))
        if duplicate_questions:
            return HarnessGateResult(
                gate_name=self.gate_name,
                passed=False,
                reason="duplicate questions",
                details={"questions": duplicate_questions},
            )

        return HarnessGateResult(gate_name=self.gate_name, passed=True)


class ScoreRangeGate(DeterministicGate):
    gate_name = "score_range"

    def evaluate(self, context: GateContext) -> HarnessGateResult:
        ranges = context.step_spec.metadata.get("score_ranges", {})
        if not ranges:
            return HarnessGateResult(gate_name=self.gate_name, passed=True, reason="no score ranges configured")
        if not isinstance(ranges, dict):
            raise HarnessValidationError("score_ranges metadata must be a dict")
        output = context.worker_result.output if context.worker_result is not None else {}
        violations: dict[str, Any] = {}
        for field_name, configured_range in ranges.items():
            if field_name == "quality_verdict.score" and context.quality_verdict is not None:
                value = context.quality_verdict.score
            else:
                value = _get_nested(output, str(field_name))
            if value is None:
                continue
            bounds = _coerce_range(configured_range)
            if not isinstance(value, int | float) or not bounds[0] <= float(value) <= bounds[1]:
                violations[str(field_name)] = {"value": value, "min": bounds[0], "max": bounds[1]}
        return HarnessGateResult(
            gate_name=self.gate_name,
            passed=not violations,
            reason=None if not violations else "score values outside configured range",
            details={"violations": violations},
        )


class BudgetGate(DeterministicGate):
    gate_name = "budget"

    def evaluate(self, context: GateContext) -> HarnessGateResult:
        if context.budget is None:
            return HarnessGateResult(gate_name=self.gate_name, passed=True, reason="no budget snapshot provided")
        violations = {}
        if context.budget.turns_used > context.budget.max_turns:
            violations["turns"] = {"used": context.budget.turns_used, "max": context.budget.max_turns}
        if context.budget.replans_used > context.budget.max_replans:
            violations["replans"] = {"used": context.budget.replans_used, "max": context.budget.max_replans}
        if context.budget.worker_calls_used > context.budget.max_worker_calls:
            violations["worker_calls"] = {
                "used": context.budget.worker_calls_used,
                "max": context.budget.max_worker_calls,
            }
        return HarnessGateResult(
            gate_name=self.gate_name,
            passed=not violations,
            reason=None if not violations else "Harness budget exceeded",
            details={"violations": violations, "snapshot": context.budget.to_dict()},
        )


class CumulativeLLMBudgetGate(DeterministicGate):
    gate_name = "cumulative_llm_budget"
    gate_version = "1"

    def evaluate(self, context: GateContext) -> HarnessGateResult:
        fact = context.cumulative_budget_fact
        if fact is None:
            return HarnessGateResult(
                gate_name=self.gate_name,
                passed=True,
                reason="no cumulative LLM budget fact",
                details={"reason_code": "budget_fact_not_applicable"},
            )
        projection = fact.control_projection()
        if fact.resolution_status != "verified":
            return HarnessGateResult(
                gate_name=self.gate_name,
                passed=False,
                reason="canonical cumulative LLM budget fact is invalid",
                details={
                    "reason_code": fact.reason_code or "budget_fact_invalid",
                    "canonical_budget_fact": projection,
                },
            )
        if not fact.within_budget:
            return HarnessGateResult(
                gate_name=self.gate_name,
                passed=False,
                reason="canonical cumulative LLM budget did not admit continuation",
                details={
                    "reason_code": (
                        "budget_usage_indeterminate"
                        if fact.indeterminate
                        else "cumulative_llm_budget_denied"
                    ),
                    "canonical_budget_fact": projection,
                },
            )
        return HarnessGateResult(
            gate_name=self.gate_name,
            passed=True,
            details={
                "reason_code": "cumulative_llm_budget_verified",
                "canonical_budget_fact": projection,
            },
        )


class SkillEvolutionBudgetGate(DeterministicGate):
    gate_name = "skill_evolution_budget"

    def evaluate(self, context: GateContext) -> HarnessGateResult:
        if context.step_spec.worker_type != HarnessWorkerType.SKILL_EVOLUTION:
            return HarnessGateResult(gate_name=self.gate_name, passed=True, reason="not a skill evolution step")
        if context.budget is None:
            return HarnessGateResult(gate_name=self.gate_name, passed=True, reason="no budget snapshot provided")
        output = context.worker_result.output if context.worker_result is not None else {}
        usage = {
            "evolution_epochs": context.budget.evolution_epochs_used + int(output.get("evolution_epochs", 0)),
            "candidates": context.budget.candidates_used + int(output.get("candidate_count", 0)),
            "patch_operations": context.budget.patch_operations_used + int(output.get("patch_operations", 0)),
            "eval_cases": context.budget.eval_cases_used + int(output.get("eval_cases", 0)),
            "sandbox_runs": context.budget.sandbox_runs_used + int(output.get("sandbox_runs", 0)),
        }
        limits = {
            "evolution_epochs": context.budget.max_evolution_epochs,
            "candidates": context.budget.max_candidates_per_run,
            "patch_operations": context.budget.max_patch_operations,
            "eval_cases": context.budget.max_eval_cases,
            "sandbox_runs": context.budget.max_sandbox_runs,
        }
        violations = {
            name: {"used": used, "max": limits[name]}
            for name, used in usage.items()
            if used > limits[name]
        }
        return HarnessGateResult(
            gate_name=self.gate_name,
            passed=not violations,
            reason=None if not violations else "skill evolution budget exceeded",
            details={"violations": violations, "usage": usage, "limits": limits},
        )


def default_plan_gates() -> tuple[DeterministicGate, ...]:
    return (ToolAllowlistGate(), DeduplicationGate(), BudgetGate(), SkillEvolutionBudgetGate())


def default_verify_gates() -> tuple[DeterministicGate, ...]:
    return (
        ToolAllowlistGate(),
        OutputSchemaGate(),
        DeduplicationGate(),
        ScoreRangeGate(),
        BudgetGate(),
        CumulativeLLMBudgetGate(),
        SkillEvolutionBudgetGate(),
    )


def all_gates_passed(results: tuple[HarnessGateResult, ...]) -> bool:
    return all(result.passed for result in results)


def _coerce_string_set(value: Any) -> set[str]:
    if value is None:
        return set()
    if isinstance(value, str):
        return {value}
    if isinstance(value, list | tuple | set | frozenset):
        return {str(item) for item in value}
    raise HarnessValidationError("metadata value must be a string sequence")


def _result_sequence(worker_result: HarnessWorkerResult | None, key: str) -> Any:
    if worker_result is None:
        return ()
    return worker_result.output.get(key, ())


def _worker_diagnostics(worker_result: HarnessWorkerResult) -> dict[str, Any]:
    diagnostics = getattr(worker_result, "diagnostics", {})
    if isinstance(diagnostics, dict):
        return diagnostics
    return {}


def _matches_json_type(value: Any, expected_type: str) -> bool:
    type_map = {
        "object": dict,
        "array": list,
        "string": str,
        "number": (int, float),
        "integer": int,
        "boolean": bool,
        "null": type(None),
    }
    expected = type_map.get(expected_type)
    if expected is None:
        raise HarnessValidationError("unsupported output schema type", details={"type": expected_type})
    if expected_type == "number" and isinstance(value, bool):
        return False
    if expected_type == "integer" and isinstance(value, bool):
        return False
    return isinstance(value, expected)


def _coerce_range(value: Any) -> tuple[float, float]:
    if isinstance(value, dict):
        return float(value["min"]), float(value["max"])
    if isinstance(value, list | tuple) and len(value) == 2:
        return float(value[0]), float(value[1])
    raise HarnessValidationError("score range must be a {min,max} dict or two-value sequence")


def _get_nested(payload: dict[str, Any], dotted_path: str) -> Any:
    current: Any = payload
    for segment in dotted_path.split("."):
        if not isinstance(current, dict):
            return None
        current = current.get(segment)
    return current


def _is_checksum(value: str) -> bool:
    if not isinstance(value, str) or not value.startswith("sha256:"):
        return False
    digest = value.removeprefix("sha256:")
    return len(digest) == 64 and all(character in "0123456789abcdef" for character in digest)


__all__ = [
    "BudgetGate",
    "CumulativeLLMBudgetGate",
    "DeduplicationGate",
    "DeterministicGate",
    "GateContext",
    "HarnessGateResult",
    "OutputSchemaGate",
    "ScoreRangeGate",
    "SkillEvolutionBudgetGate",
    "ToolAllowlistGate",
    "all_gates_passed",
    "default_plan_gates",
    "default_verify_gates",
]
