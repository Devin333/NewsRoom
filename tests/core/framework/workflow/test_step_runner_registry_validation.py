from core.framework.specs import StepSpec, StepStatus, StepType, WorkflowSpec
from core.framework.workflow import (
    FunctionStepRegistry,
    FunctionStepRunner,
    ScopedDataBuffer,
    StepOutcome,
    StepRunnerCapability,
    StepRunnerRegistry,
    StepRunnerSideEffectLevel,
    ValidationErrorItem,
    WorkflowCompileIssueCode,
    WorkflowCompiler,
    build_default_step_runner_registry,
    build_runner_manifest,
)


def test_validate_workflow_passes_when_step_type_has_runner() -> None:
    registry = StepRunnerRegistry()
    registry.register(_FakeRunner())

    result = registry.validate_workflow(_workflow(StepSpec("finish", "known", write_keys=["out"])))

    assert result.passed is True


def test_validate_workflow_fails_when_step_type_has_no_runner() -> None:
    registry = StepRunnerRegistry()

    result = registry.validate_workflow(
        _workflow(StepSpec("finish", "artifact.write", step_type=StepType.ARTIFACT))
    )

    assert not result.passed
    assert result.errors[0].code == "runner_not_found"


def test_validate_workflow_fails_when_implementation_cannot_resolve() -> None:
    registry = StepRunnerRegistry()
    registry.register(_FakeRunner())

    result = registry.validate_workflow(_workflow(StepSpec("finish", "unknown")))

    assert not result.passed
    assert result.errors[0].code == "implementation_not_resolvable"


def test_validate_workflow_reports_missing_dependencies() -> None:
    registry = StepRunnerRegistry()
    registry.register(_DependencyRunner())

    result = registry.validate_workflow(_workflow(StepSpec("finish", "needs.dep")))

    assert not result.passed
    error = result.errors[0]
    assert error.code == "runner_missing_dependencies"
    assert "dep" in error.details["missing_dependencies"]


def test_default_registry_reports_missing_dependencies_for_dependency_bound_step() -> None:
    registry = build_default_step_runner_registry(FunctionStepRegistry())

    result = registry.validate_workflow(
        _workflow(
            StepSpec(
                "finish",
                "tools.call",
                step_type=StepType.TOOL_CALL,
                metadata={"tool_name": "report.validate"},
            )
        )
    )

    assert not result.passed
    error = result.errors[0]
    assert error.code == "runner_missing_dependencies"
    assert error.runner_id == "builtin.tool"
    assert error.details["missing_dependencies"] == ["tool_registry"]


def test_validate_workflow_includes_runner_validate_step_errors() -> None:
    registry = StepRunnerRegistry(available_dependencies={"dep"})
    registry.register(_InvalidStepRunner())

    result = registry.validate_workflow(_workflow(StepSpec("finish", "invalid")))

    assert not result.passed
    assert result.errors[0].code == "fake_invalid_step"
    assert result.errors[0].runner_id == "fake.invalid"


def test_registry_health_check_reports_missing_dependencies() -> None:
    registry = StepRunnerRegistry()
    registry.register(_DependencyRunner())

    health = registry.health_check()

    assert not health.ok
    assert health.items[0].missing_dependencies == ["dep"]


def test_compiler_maps_registry_validation_errors() -> None:
    registry = StepRunnerRegistry()
    registry.register(_FakeRunner())

    result = WorkflowCompiler(runner_registry=registry).compile(
        _workflow(StepSpec("finish", "unknown"))
    )

    assert not result.passed
    assert result.has_error(WorkflowCompileIssueCode.RUNNER_IMPLEMENTATION_NOT_FOUND)


def test_compiler_maps_missing_dependency_errors() -> None:
    registry = StepRunnerRegistry()
    registry.register(_DependencyRunner())

    result = WorkflowCompiler(runner_registry=registry).compile(
        _workflow(StepSpec("finish", "needs.dep"))
    )

    assert not result.passed
    assert result.has_error(WorkflowCompileIssueCode.RUNNER_MISSING_DEPENDENCY)


def test_runner_version_enters_manifest() -> None:
    registry = StepRunnerRegistry()
    registry.register(_FakeRunner())
    workflow = _workflow(StepSpec("finish", "known"))

    manifest = build_runner_manifest(workflow, registry)

    item = manifest.runners[0]
    assert item.runner_id == "fake.function"
    assert item.runner_version == "1.0.0"


def test_compile_result_contains_runner_manifest() -> None:
    functions = FunctionStepRegistry()
    functions.register("sample.finish", lambda buffer: {"report": "ok"})
    registry = StepRunnerRegistry.with_function_runner(FunctionStepRunner(functions))

    result = WorkflowCompiler(runner_registry=registry).compile(
        _workflow(StepSpec("finish", "sample.finish", write_keys=["report"]))
    )

    assert result.passed
    assert result.runner_manifest is not None
    assert result.runner_manifest.runners[0].runner_id == "builtin.function"


def test_default_registry_can_report_dependency_bound_health() -> None:
    registry = build_default_step_runner_registry(
        FunctionStepRegistry(),
        tool_registry=object(),
    )

    health = registry.health_check()

    assert not health.ok
    missing = {
        item.runner_id: item.missing_dependencies
        for item in health.items
        if item.missing_dependencies
    }
    assert missing["builtin.agent_loop"] == ["agent_registry", "llm_client"]
    assert missing["builtin.artifact"] == ["artifact_publisher"]
    assert missing["builtin.human_review"] == ["human_review_store"]
    assert missing["builtin.subworkflow"] == ["workflow_executor"]


class _FakeRunner:
    capability = StepRunnerCapability(
        step_type=StepType.FUNCTION,
        runner_id="fake.function",
        version="1.0.0",
        supports_checkpoint=True,
        supports_resume=True,
        supports_timeout=True,
        supports_retry=True,
        side_effect_level=StepRunnerSideEffectLevel.NONE,
        supported_implementations=["known"],
    )

    def can_resolve(self, step: StepSpec) -> bool:
        return (
            step.step_type == StepType.FUNCTION
            and step.implementation in self.capability.supported_implementations
        )

    def validate_step(self, step: StepSpec) -> list[ValidationErrorItem]:
        return []

    def run(self, step: StepSpec, buffer: ScopedDataBuffer) -> StepOutcome:
        return StepOutcome(status=StepStatus.SUCCEEDED)


class _DependencyRunner(_FakeRunner):
    capability = StepRunnerCapability(
        step_type=StepType.FUNCTION,
        runner_id="fake.dependency",
        version="1.0.0",
        supports_checkpoint=True,
        supports_resume=True,
        supports_timeout=True,
        supports_retry=True,
        side_effect_level=StepRunnerSideEffectLevel.READ_ONLY,
        required_dependencies=["dep"],
        supported_implementations=["needs.dep"],
    )


class _InvalidStepRunner(_FakeRunner):
    capability = StepRunnerCapability(
        step_type=StepType.FUNCTION,
        runner_id="fake.invalid",
        version="1.0.0",
        supports_checkpoint=True,
        supports_resume=True,
        supports_timeout=True,
        supports_retry=True,
        side_effect_level=StepRunnerSideEffectLevel.NONE,
        required_dependencies=["dep"],
        supported_implementations=["invalid"],
    )

    def validate_step(self, step: StepSpec) -> list[ValidationErrorItem]:
        return [
            ValidationErrorItem(
                code="fake_invalid_step",
                message="Fake invalid step.",
                field="implementation",
            )
        ]


def _workflow(step: StepSpec) -> WorkflowSpec:
    return WorkflowSpec(
        workflow_id="runner-validation",
        name="Runner Validation",
        version="1.0",
        start_step_id=step.step_id,
        terminal_step_ids=[step.step_id],
        steps=[step],
    )
