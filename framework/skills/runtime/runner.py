"""Skill execution runner."""

from __future__ import annotations

from uuid import uuid4

from framework.skills.core.context import SkillRunContext
from framework.skills.core.errors import SkillMetadataError, SkillNotFoundError, SkillPackageError
from framework.skills.core.result import SkillCost, SkillFailureReason, SkillResult, SkillRunStatus
from framework.skills.package.loader import SkillPackage, SkillPackageLoader
from framework.skills.package.registry import SkillRegistry
from framework.skills.quality.gates import SchemaValidGate, SkillQualityGateRunner
from framework.skills.runtime.executor import MockSkillExecutor, SkillExecutor
from framework.skills.runtime.prompt import SkillPromptBuilder
from framework.skills.tracing.trace import SkillTraceRecorder
from framework.skills.validation.schema import SkillSchemaValidator


class SkillRunner:
    def __init__(
        self,
        registry: SkillRegistry,
        package_loader: SkillPackageLoader | None = None,
        schema_validator: SkillSchemaValidator | None = None,
        prompt_builder: SkillPromptBuilder | None = None,
        executor: SkillExecutor | None = None,
        quality_runner: SkillQualityGateRunner | None = None,
    ) -> None:
        self.registry = registry
        self.package_loader = package_loader or SkillPackageLoader()
        self.schema_validator = schema_validator or SkillSchemaValidator()
        self.prompt_builder = prompt_builder or SkillPromptBuilder()
        self.executor = executor or MockSkillExecutor()
        if quality_runner is None:
            self.quality_runner = SkillQualityGateRunner([SchemaValidGate(self.schema_validator)])
        else:
            self.quality_runner = quality_runner

    def run(self, skill_name: str, input_data: dict, context: SkillRunContext | None = None) -> SkillResult:
        """Resolve, validate, execute, gate, and return a structured result."""
        context = context or SkillRunContext(run_id=str(uuid4()), skill_name=skill_name)
        trace = SkillTraceRecorder()
        trace.record("skill.run.started", skill_name, "skill run started", {"run_id": context.run_id})
        version = "unknown"

        try:
            package = self._resolve_package(skill_name)
            version = package.metadata.version
            trace.record("skill.package.resolved", skill_name, "skill package resolved", {"version": version})
        except SkillNotFoundError as exc:
            return self._traced_failure(
                trace,
                skill_name,
                version,
                SkillFailureReason.SKILL_NOT_FOUND,
                "skill_not_found",
                str(exc),
            )
        except (SkillPackageError, SkillMetadataError) as exc:
            return self._traced_failure(
                trace,
                skill_name,
                version,
                SkillFailureReason.PACKAGE_INVALID,
                "package_invalid",
                str(exc),
            )
        except Exception as exc:
            return self._traced_failure(
                trace,
                skill_name,
                version,
                SkillFailureReason.PACKAGE_INVALID,
                "package_invalid",
                str(exc),
            )

        input_validation = self.schema_validator.validate_input(package, input_data)
        if not input_validation.ok:
            result = self._failed_result(
                skill_name,
                version,
                SkillFailureReason.INPUT_SCHEMA_INVALID,
                "input_schema_invalid",
                "skill input failed schema validation",
            )
            result.errors = input_validation.errors_as_skill_details()
            trace.record("skill.input.invalid", skill_name, "input schema validation failed")
            result.trace = trace.to_dict()
            return result
        trace.record("skill.input.validated", skill_name, "input schema validation passed")

        try:
            prompt_bundle = self.prompt_builder.build(package, input_data, context)
            trace.record("skill.prompt.built", skill_name, "prompt bundle built")
        except Exception as exc:
            return self._traced_failure(
                trace,
                skill_name,
                version,
                SkillFailureReason.PACKAGE_INVALID,
                "prompt_build_failed",
                str(exc),
            )

        try:
            output = self.executor.execute(package, input_data, prompt_bundle, context)
            trace.record("skill.executor.completed", skill_name, "skill executor completed")
        except TimeoutError as exc:
            return self._traced_failure(
                trace,
                skill_name,
                version,
                SkillFailureReason.TIMEOUT,
                "timeout",
                str(exc),
            )
        except Exception as exc:
            return self._traced_failure(
                trace,
                skill_name,
                version,
                SkillFailureReason.EXECUTION_FAILED,
                "execution_failed",
                str(exc),
            )

        output_validation = self.schema_validator.validate_output(package, output.data)
        if not output_validation.ok:
            result = self._failed_result(
                skill_name,
                version,
                SkillFailureReason.OUTPUT_SCHEMA_INVALID,
                "output_schema_invalid",
                "skill output failed schema validation",
            )
            result.output = output.data
            result.evidence = output.evidence
            result.warnings = output.warnings
            result.errors = output_validation.errors_as_skill_details()
            trace.record("skill.output.invalid", skill_name, "output schema validation failed")
            result.trace = trace.to_dict()
            return result
        trace.record("skill.output.validated", skill_name, "output schema validation passed")

        gate_results = self.quality_runner.run(package, input_data, output.data, context)
        gate_payload = [gate.model_dump(mode="json") for gate in gate_results]
        failed_gates = [gate for gate in gate_results if not gate.passed]
        if failed_gates:
            schema_failed = any(gate.gate_name == "schema_valid" for gate in failed_gates)
            result = SkillResult(
                skill_name=skill_name,
                version=version,
                status=SkillRunStatus.FAILED if schema_failed else SkillRunStatus.PARTIAL,
                failure_reason=SkillFailureReason.QUALITY_GATE_FAILED,
                output=output.data,
                warnings=output.warnings,
                evidence=output.evidence,
                quality_gate_results=gate_payload,
                cost=SkillCost(),
            )
            result.add_error(
                "quality_gate_failed",
                "one or more skill quality gates failed",
                detail={"failed_gates": [gate.gate_name for gate in failed_gates]},
            )
            trace.record(
                "skill.quality.failed",
                skill_name,
                "quality gate failed",
                {"failed_gates": [gate.gate_name for gate in failed_gates]},
            )
            result.trace = trace.to_dict()
            return result

        trace.record("skill.run.completed", skill_name, "skill run completed")
        return SkillResult.success(
            skill_name=skill_name,
            version=version,
            output=output.data,
            evidence=output.evidence,
            quality_gate_results=gate_payload,
            trace=trace.to_dict(),
        )

    def _resolve_package(self, skill_name: str) -> SkillPackage:
        metadata = self.registry.get(skill_name)
        if metadata is None:
            raise SkillNotFoundError(f"skill not found: {skill_name}")
        package = self.registry.get_package(skill_name)
        if package is not None:
            return package
        package = self.package_loader.load(metadata.path)
        self.registry.register_package(package)
        return package

    def _failed_result(
        self,
        skill_name: str,
        version: str,
        reason: SkillFailureReason,
        code: str,
        message: str,
    ) -> SkillResult:
        return SkillResult.failed(skill_name=skill_name, version=version, reason=reason, code=code, message=message)

    def _traced_failure(
        self,
        trace: SkillTraceRecorder,
        skill_name: str,
        version: str,
        reason: SkillFailureReason,
        code: str,
        message: str,
    ) -> SkillResult:
        result = self._failed_result(skill_name, version, reason, code, message)
        trace.record("skill.run.failed", skill_name, message, {"reason": reason.value})
        result.trace = trace.to_dict()
        return result
