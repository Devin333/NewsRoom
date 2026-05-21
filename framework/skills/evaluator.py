"""Skill evaluator for local example cases."""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel, Field

from framework.skills.context import SkillRunContext
from framework.skills.package import SkillPackage
from framework.skills.registry import SkillRegistry
from framework.skills.result import SkillFailureReason
from framework.skills.runner import SkillRunner


class SkillEvalCase(BaseModel):
    case_id: str
    input_path: str
    expected_path: str | None = None
    input_data: dict
    expected_data: dict | None = None


class SkillEvalCaseResult(BaseModel):
    case_id: str
    passed: bool
    result_status: str
    schema_passed: bool
    quality_gates_passed: bool
    diffs: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)


class SkillEvalResult(BaseModel):
    skill_name: str
    version: str
    total_cases: int
    passed_cases: int
    failed_cases: int
    schema_pass_rate: float
    quality_gate_pass_rate: float
    example_pass_rate: float
    case_results: list[SkillEvalCaseResult] = Field(default_factory=list)

    def passed(self) -> bool:
        return self.failed_cases == 0


class SkillEvaluator:
    def __init__(self, registry: SkillRegistry, runner: SkillRunner) -> None:
        self.registry = registry
        self.runner = runner

    def load_cases(self, package: SkillPackage) -> list[SkillEvalCase]:
        root = package.root() / "examples"
        if not root.is_dir():
            return []
        cases: list[SkillEvalCase] = []
        for input_path in sorted(root.glob("*.input.json"), key=lambda item: item.name):
            case_id = input_path.name[: -len(".input.json")]
            expected_path = root / f"{case_id}.expected.json"
            cases.append(
                SkillEvalCase(
                    case_id=case_id,
                    input_path=str(input_path),
                    expected_path=str(expected_path) if expected_path.is_file() else None,
                    input_data=_load_json(input_path),
                    expected_data=_load_json(expected_path) if expected_path.is_file() else None,
                )
            )
        return cases

    def evaluate(self, skill_name: str) -> SkillEvalResult:
        package = self.runner._resolve_package(skill_name)
        cases = self.load_cases(package)
        case_results: list[SkillEvalCaseResult] = []
        schema_passed_count = 0
        quality_passed_count = 0

        for case in cases:
            context = SkillRunContext(
                run_id=f"eval:{case.case_id}",
                skill_name=skill_name,
                caller_type="evaluator",
                caller_id=case.case_id,
                metadata={"case_id": case.case_id},
            )
            result = self.runner.run(skill_name, case.input_data, context)
            schema_passed = result.failure_reason not in {
                SkillFailureReason.INPUT_SCHEMA_INVALID,
                SkillFailureReason.OUTPUT_SCHEMA_INVALID,
            }
            quality_gates_passed = all(gate.get("passed") for gate in result.quality_gate_results)
            example_passed, diffs = self.compare_output(result.output, case.expected_data)
            errors = [error.message for error in result.errors]
            passed = result.is_success() and schema_passed and quality_gates_passed and example_passed
            if schema_passed:
                schema_passed_count += 1
            if quality_gates_passed:
                quality_passed_count += 1
            case_results.append(
                SkillEvalCaseResult(
                    case_id=case.case_id,
                    passed=passed,
                    result_status=result.status.value,
                    schema_passed=schema_passed,
                    quality_gates_passed=quality_gates_passed,
                    diffs=diffs,
                    errors=errors,
                )
            )

        total = len(cases)
        passed_cases = sum(1 for case in case_results if case.passed)
        failed_cases = total - passed_cases
        return SkillEvalResult(
            skill_name=package.metadata.name,
            version=package.metadata.version,
            total_cases=total,
            passed_cases=passed_cases,
            failed_cases=failed_cases,
            schema_pass_rate=_rate(schema_passed_count, total),
            quality_gate_pass_rate=_rate(quality_passed_count, total),
            example_pass_rate=_rate(passed_cases, total),
            case_results=case_results,
        )

    def compare_output(self, actual: dict, expected: dict | None) -> tuple[bool, list[str]]:
        """Compare expected top-level keys with actual output."""
        if expected is None:
            return (bool(actual), [] if actual else ["actual output is empty"])
        diffs: list[str] = []
        for key, expected_value in expected.items():
            if key not in actual:
                diffs.append(f"missing key: {key}")
                continue
            if actual[key] != expected_value:
                diffs.append(f"value mismatch for {key}: expected {expected_value!r}, got {actual[key]!r}")
        return (not diffs, diffs)


def _load_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    return payload if isinstance(payload, dict) else {"value": payload}


def _rate(count: int, total: int) -> float:
    return count / total if total else 0.0
