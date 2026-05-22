"""Quality gates for skill outputs."""

from __future__ import annotations

from typing import Protocol

from pydantic import BaseModel, Field

from framework.skills.core.context import SkillRunContext
from framework.skills.package.loader import SkillPackage
from framework.skills.validation.schema import SkillSchemaValidator


class SkillQualityGateResult(BaseModel):
    gate_name: str
    passed: bool
    score: float | None = None
    message: str = ""
    details: dict = Field(default_factory=dict)


class SkillQualityGate(Protocol):
    name: str

    def evaluate(
        self,
        package: SkillPackage,
        input_data: dict,
        output_data: dict,
        context: SkillRunContext,
    ) -> SkillQualityGateResult:
        ...


class NoEmptyOutputGate:
    name = "no_empty_output"

    def evaluate(
        self,
        package: SkillPackage,
        input_data: dict,
        output_data: dict,
        context: SkillRunContext,
    ) -> SkillQualityGateResult:
        _ = package, input_data, context
        passed = _has_non_empty_value(output_data)
        return SkillQualityGateResult(
            gate_name=self.name,
            passed=passed,
            score=1.0 if passed else 0.0,
            message="output is non-empty" if passed else "output is empty",
        )


class EvidenceRequiredGate:
    name = "evidence_required"

    def evaluate(
        self,
        package: SkillPackage,
        input_data: dict,
        output_data: dict,
        context: SkillRunContext,
    ) -> SkillQualityGateResult:
        _ = package, input_data, context
        passed = _has_evidence(output_data)
        return SkillQualityGateResult(
            gate_name=self.name,
            passed=passed,
            score=1.0 if passed else 0.0,
            message="evidence found" if passed else "evidence is required",
        )


class SchemaValidGate:
    name = "schema_valid"

    def __init__(self, schema_validator: SkillSchemaValidator):
        self.schema_validator = schema_validator

    def evaluate(
        self,
        package: SkillPackage,
        input_data: dict,
        output_data: dict,
        context: SkillRunContext,
    ) -> SkillQualityGateResult:
        _ = input_data, context
        result = self.schema_validator.validate_output(package, output_data)
        return SkillQualityGateResult(
            gate_name=self.name,
            passed=result.ok,
            score=1.0 if result.ok else 0.0,
            message="output schema valid" if result.ok else "output schema invalid",
            details={"issues": [issue.model_dump(mode="json") for issue in result.issues]},
        )


class NoErrorStatusGate:
    name = "no_error_status"

    def evaluate(
        self,
        package: SkillPackage,
        input_data: dict,
        output_data: dict,
        context: SkillRunContext,
    ) -> SkillQualityGateResult:
        _ = package, input_data, context
        status = str(output_data.get("status", "")).lower()
        errors = output_data.get("errors")
        passed = status not in {"error", "failed", "failure"} and not _has_non_empty_value(errors)
        return SkillQualityGateResult(
            gate_name=self.name,
            passed=passed,
            score=1.0 if passed else 0.0,
            message="no error status" if passed else "output carries an error status",
        )


class SkillQualityGateRunner:
    def __init__(self, gates: list[SkillQualityGate] | None = None):
        self._gates: dict[str, SkillQualityGate] = {}
        self.register(NoEmptyOutputGate())
        self.register(EvidenceRequiredGate())
        self.register(NoErrorStatusGate())
        self.register(SchemaValidGate(SkillSchemaValidator()))
        for gate in gates or []:
            self.register(gate)

    def register(self, gate: SkillQualityGate) -> None:
        self._gates[_normalize_gate_name(gate.name)] = gate

    def get(self, name: str) -> SkillQualityGate | None:
        return self._gates.get(_normalize_gate_name(name))

    def run(
        self,
        package: SkillPackage,
        input_data: dict,
        output_data: dict,
        context: SkillRunContext,
    ) -> list[SkillQualityGateResult]:
        """Run gates declared by metadata, or the default non-empty/schema gates."""
        gate_names = [_normalize_gate_name(name) for name in package.metadata.quality_gates]
        if not gate_names:
            gate_names = ["no_empty_output"]
            if package.metadata.output_schema:
                gate_names.append("schema_valid")

        results: list[SkillQualityGateResult] = []
        for name in gate_names:
            gate = self.get(name)
            if gate is None:
                results.append(
                    SkillQualityGateResult(
                        gate_name=name,
                        passed=False,
                        message=f"unknown quality gate: {name}",
                        details={"code": "unknown_quality_gate"},
                    )
                )
                continue
            try:
                results.append(gate.evaluate(package, input_data, output_data, context))
            except Exception as exc:
                results.append(
                    SkillQualityGateResult(
                        gate_name=name,
                        passed=False,
                        message=str(exc),
                        details={"code": "quality_gate_exception", "exception_type": type(exc).__name__},
                    )
                )
        return results


def _normalize_gate_name(name: str) -> str:
    return str(name).strip().lower().replace("-", "_")


def _has_evidence(output_data: dict) -> bool:
    for key in ("evidence", "citations", "supporting_sources", "evidence_spans"):
        if _has_non_empty_value(output_data.get(key)):
            return True
    claim_results = output_data.get("claim_results")
    if isinstance(claim_results, list):
        return any(
            isinstance(claim, dict) and _has_non_empty_value(claim.get("evidence_spans"))
            for claim in claim_results
        )
    return False


def _has_non_empty_value(value) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, dict):
        return any(_has_non_empty_value(item) for item in value.values())
    if isinstance(value, (list, tuple, set)):
        return any(_has_non_empty_value(item) for item in value)
    return True
