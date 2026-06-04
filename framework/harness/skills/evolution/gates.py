from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from framework.harness.control_plane.errors import HarnessValidationError
from framework.harness.skills.evolution.models import (
    FORBIDDEN_SKILL_PATCH_OPERATIONS,
    SkillCandidate,
    SkillEvaluationResult,
    SkillEvolutionBudget,
    SkillPatchSet,
)
from framework.shared.json import to_jsonable


REQUIRED_QUALITY_GATES = frozenset({"schema_valid", "evidence_required", "no_empty_output"})
HIGH_RISK_TOOLS = frozenset({"shell", "filesystem_write", "database_write", "network_post"})
SECRET_PATTERNS = (
    re.compile(r"sk-[A-Za-z0-9_-]{12,}"),
    re.compile(r"(?i)(api[_-]?key|secret|token)\s*[:=]\s*[A-Za-z0-9_\-]{12,}"),
)


@dataclass(frozen=True)
class SkillEvolutionGateResult:
    gate_name: str
    passed: bool
    reason: str | None = None
    details: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not str(self.gate_name).strip():
            raise HarnessValidationError("gate_name is required")
        object.__setattr__(self, "details", dict(self.details))

    def to_dict(self) -> dict[str, Any]:
        return {
            "gate": self.gate_name,
            "passed": self.passed,
            "reason": self.reason,
            "details": to_jsonable(self.details),
        }


class SkillPackageStructureGate:
    gate_name = "skill_package_structure"

    def evaluate(self, candidate: SkillCandidate) -> SkillEvolutionGateResult:
        manifest = candidate.manifest_snapshot
        files = set(manifest.get("files", ()))
        missing = []
        if "SKILL.md" not in files and "SKILL.md" not in manifest:
            missing.append("SKILL.md")
        if manifest.get("input_schema") and manifest["input_schema"] not in files:
            missing.append(str(manifest["input_schema"]))
        if manifest.get("output_schema") and manifest["output_schema"] not in files:
            missing.append(str(manifest["output_schema"]))
        return SkillEvolutionGateResult(
            self.gate_name,
            not missing,
            None if not missing else "candidate package is missing required files",
            {"missing": missing},
        )


class SkillManifestGate:
    gate_name = "skill_manifest"

    def evaluate(self, candidate: SkillCandidate) -> SkillEvolutionGateResult:
        metadata = dict(candidate.manifest_snapshot.get("metadata", candidate.manifest_snapshot))
        missing = [field for field in ("name", "version", "risk_level", "owner") if not metadata.get(field)]
        return SkillEvolutionGateResult(
            self.gate_name,
            not missing,
            None if not missing else "candidate manifest is missing required fields",
            {"missing": missing},
        )


class SkillSchemaCompatibilityGate:
    gate_name = "skill_schema_compatibility"

    def evaluate(self, candidate: SkillCandidate) -> SkillEvolutionGateResult:
        metadata = dict(candidate.manifest_snapshot.get("metadata", candidate.manifest_snapshot))
        broken = []
        for field_name in ("input_schema", "output_schema"):
            schema = metadata.get(field_name) or candidate.manifest_snapshot.get(field_name)
            if schema and not str(schema).endswith(".json"):
                broken.append(field_name)
        removed_required = [
            operation.path
            for operation in candidate.patch_set.operations
            if operation.op == "delete_section" and "schema" in operation.path.lower()
        ]
        return SkillEvolutionGateResult(
            self.gate_name,
            not broken and not removed_required,
            None if not broken and not removed_required else "candidate breaks schema compatibility",
            {"invalid_schema_fields": broken, "removed_required_schema": removed_required},
        )


class SkillAllowedToolsGate:
    gate_name = "skill_allowed_tools"

    def evaluate(self, candidate: SkillCandidate, *, approval_ref: str | None = None) -> SkillEvolutionGateResult:
        metadata = dict(candidate.manifest_snapshot.get("metadata", candidate.manifest_snapshot))
        allowed_tools = {str(tool) for tool in metadata.get("allowed_tools", ())}
        high_risk = sorted(allowed_tools.intersection(HIGH_RISK_TOOLS))
        passed = not high_risk or bool(approval_ref or candidate.metadata.get("approval_ref"))
        return SkillEvolutionGateResult(
            self.gate_name,
            passed,
            None if passed else "high risk allowed_tools require approval",
            {"high_risk_tools": high_risk, "approval_ref": approval_ref or candidate.metadata.get("approval_ref")},
        )


class SkillPatchBudgetGate:
    gate_name = "skill_patch_budget"

    def evaluate(self, patch_set: SkillPatchSet, budget: SkillEvolutionBudget) -> SkillEvolutionGateResult:
        changed_files = set(patch_set.changed_files)
        changed_files.update(_file_from_path(operation.path) for operation in patch_set.operations)
        violations = {}
        if len(patch_set.operations) > budget.max_patch_operations:
            violations["patch_operations"] = {"used": len(patch_set.operations), "max": budget.max_patch_operations}
        if len(changed_files) > budget.max_changed_files:
            violations["changed_files"] = {"used": len(changed_files), "max": budget.max_changed_files}
        return SkillEvolutionGateResult(
            self.gate_name,
            not violations,
            None if not violations else "skill patch budget exceeded",
            {"violations": violations, "changed_files": sorted(changed_files)},
        )


class SkillNoSecretGate:
    gate_name = "skill_no_secret"

    def evaluate(self, candidate: SkillCandidate) -> SkillEvolutionGateResult:
        text = " ".join(_string_values(candidate.to_dict()))
        matches = [pattern.pattern for pattern in SECRET_PATTERNS if pattern.search(text)]
        return SkillEvolutionGateResult(
            self.gate_name,
            not matches,
            None if not matches else "candidate contains secret-like material",
            {"matched_patterns": matches},
        )


class SkillDomainBoundaryGate:
    gate_name = "skill_domain_boundary"

    def evaluate(self, candidate: SkillCandidate) -> SkillEvolutionGateResult:
        text = " ".join(_string_values(candidate.to_dict()))
        violations = []
        if candidate.base_version.skill_name.startswith("framework.") and "business/research" in text:
            violations.append("framework_skill_contains_research_rule")
        if "business.boards.paper_radar" in text or "paper_radar" in text:
            violations.append("candidate_leaks_legacy_paper_radar")
        return SkillEvolutionGateResult(
            self.gate_name,
            not violations,
            None if not violations else "candidate crosses skill domain boundary",
            {"violations": violations},
        )


class SkillQualityGateRetentionGate:
    gate_name = "skill_quality_gate_retention"

    def evaluate(self, candidate: SkillCandidate) -> SkillEvolutionGateResult:
        removed = [
            operation.path
            for operation in candidate.patch_set.operations
            if operation.op in {"delete_section", "replace_section", "replace"}
            and any(gate in str(operation.path) for gate in REQUIRED_QUALITY_GATES)
        ]
        replacement_gates: set[str] | None = None
        for operation in candidate.patch_set.operations:
            if "quality_gates" in operation.path and isinstance(operation.value, (list, tuple)):
                replacement_gates = {str(item) for item in operation.value}
        missing_required = sorted(REQUIRED_QUALITY_GATES - replacement_gates) if replacement_gates is not None else []
        passed = not removed and not missing_required
        return SkillEvolutionGateResult(
            self.gate_name,
            passed,
            None if passed else "candidate removes required quality gate",
            {"removed": removed, "missing_required": missing_required},
        )


class SkillPatchOperationGate:
    gate_name = "skill_patch_operation"

    def evaluate(self, patch_set: SkillPatchSet) -> SkillEvolutionGateResult:
        forbidden = sorted(operation.op for operation in patch_set.operations if operation.op in FORBIDDEN_SKILL_PATCH_OPERATIONS)
        return SkillEvolutionGateResult(
            self.gate_name,
            not forbidden,
            None if not forbidden else "patch contains forbidden operation",
            {"forbidden": forbidden},
        )


class SkillEvalImprovementGate:
    gate_name = "skill_eval_improvement"

    def evaluate(self, evaluation: SkillEvaluationResult) -> SkillEvolutionGateResult:
        if evaluation.baseline_score is None:
            return SkillEvolutionGateResult(self.gate_name, evaluation.passed, "no baseline configured", evaluation.to_dict())
        improvement = evaluation.score - evaluation.baseline_score
        passed = evaluation.passed and improvement >= evaluation.minimum_improvement
        return SkillEvolutionGateResult(
            self.gate_name,
            passed,
            None if passed else "held-out eval did not improve enough",
            {"improvement": improvement, "minimum_improvement": evaluation.minimum_improvement},
        )


class SkillRegressionGate:
    gate_name = "skill_regression"

    def evaluate(self, evaluation: SkillEvaluationResult) -> SkillEvolutionGateResult:
        regressions = {
            key: value
            for key, value in evaluation.metrics.items()
            if key.endswith("_regression") and float(value) > evaluation.regression_tolerance
        }
        coverage_regressed = bool(evaluation.metrics.get("evidence_coverage_regressed", False))
        passed = not regressions and not coverage_regressed
        return SkillEvolutionGateResult(
            self.gate_name,
            passed,
            None if passed else "candidate regressed a critical metric",
            {"regressions": regressions, "evidence_coverage_regressed": coverage_regressed},
        )


class SkillPromotionGate:
    gate_name = "skill_promotion"

    def evaluate(
        self,
        candidate: SkillCandidate,
        evaluation: SkillEvaluationResult,
        *,
        approval_ref: str | None = None,
    ) -> SkillEvolutionGateResult:
        eval_gate = SkillEvalImprovementGate().evaluate(evaluation)
        regression_gate = SkillRegressionGate().evaluate(evaluation)
        tools_gate = SkillAllowedToolsGate().evaluate(candidate, approval_ref=approval_ref)
        passed = eval_gate.passed and regression_gate.passed and tools_gate.passed
        return SkillEvolutionGateResult(
            self.gate_name,
            passed,
            None if passed else "candidate is not eligible for promotion",
            {"gate_results": [eval_gate.to_dict(), regression_gate.to_dict(), tools_gate.to_dict()]},
        )


class SkillStaticGateSuite:
    def __init__(self, budget: SkillEvolutionBudget | None = None) -> None:
        self.budget = budget or SkillEvolutionBudget()
        self.package_structure = SkillPackageStructureGate()
        self.manifest = SkillManifestGate()
        self.schema_compatibility = SkillSchemaCompatibilityGate()
        self.allowed_tools = SkillAllowedToolsGate()
        self.patch_budget = SkillPatchBudgetGate()
        self.no_secret = SkillNoSecretGate()
        self.domain_boundary = SkillDomainBoundaryGate()
        self.quality_gate_retention = SkillQualityGateRetentionGate()
        self.patch_operation = SkillPatchOperationGate()

    def evaluate(self, candidate: SkillCandidate) -> tuple[SkillEvolutionGateResult, ...]:
        return (
            self.package_structure.evaluate(candidate),
            self.manifest.evaluate(candidate),
            self.schema_compatibility.evaluate(candidate),
            self.allowed_tools.evaluate(candidate),
            self.patch_budget.evaluate(candidate.patch_set, self.budget),
            self.no_secret.evaluate(candidate),
            self.domain_boundary.evaluate(candidate),
            self.quality_gate_retention.evaluate(candidate),
            self.patch_operation.evaluate(candidate.patch_set),
        )


def failed_skill_gate_dicts(results: tuple[SkillEvolutionGateResult, ...]) -> tuple[dict[str, Any], ...]:
    return tuple(result.to_dict() for result in results if result.passed is False)


def _file_from_path(path: str) -> str:
    normalized = str(path).replace("\\", "/").strip("/")
    if not normalized:
        return "SKILL.md"
    return normalized.split("#", 1)[0].split("/", 1)[0] or "SKILL.md"


def _string_values(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        values: list[str] = []
        for key, item in value.items():
            values.extend(_string_values(key))
            values.extend(_string_values(item))
        return values
    if isinstance(value, (list, tuple, set)):
        values = []
        for item in value:
            values.extend(_string_values(item))
        return values
    return []


__all__ = [
    "SkillAllowedToolsGate",
    "SkillDomainBoundaryGate",
    "SkillEvalImprovementGate",
    "SkillEvolutionGateResult",
    "SkillManifestGate",
    "SkillNoSecretGate",
    "SkillPackageStructureGate",
    "SkillPatchBudgetGate",
    "SkillPatchOperationGate",
    "SkillPromotionGate",
    "SkillQualityGateRetentionGate",
    "SkillRegressionGate",
    "SkillSchemaCompatibilityGate",
    "SkillStaticGateSuite",
    "failed_skill_gate_dicts",
]
