from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, cast

from framework.specs import StepSpec, StepType, WorkflowSpec
from framework.workflow.runners.base import (
    StepExecutionError,
    StepRunner,
    StepRunnerCapability,
    StepRunnerSideEffectLevel,
    ValidationErrorItem,
    default_runner_can_resolve,
)


class StepRunnerRegistryError(StepExecutionError):
    """Raised when StepRunnerRegistry cannot register or resolve a runner."""


class StepRunnerHealthStatus(StrEnum):
    OK = "ok"
    DEGRADED = "degraded"
    ERROR = "error"


@dataclass(frozen=True)
class StepRunnerDescriptor:
    step_type: StepType
    runner_id: str
    version: str
    supports_checkpoint: bool
    supports_resume: bool
    supports_timeout: bool
    supports_retry: bool
    side_effect_level: str
    required_dependencies: list[str]
    available: bool
    missing_dependencies: list[str]
    description: str | None = None
    supported_implementations: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "step_type": self.step_type.value,
            "runner_id": self.runner_id,
            "version": self.version,
            "supports_checkpoint": self.supports_checkpoint,
            "supports_resume": self.supports_resume,
            "supports_timeout": self.supports_timeout,
            "supports_retry": self.supports_retry,
            "side_effect_level": self.side_effect_level,
            "required_dependencies": list(self.required_dependencies),
            "available": self.available,
            "missing_dependencies": list(self.missing_dependencies),
            "description": self.description,
            "supported_implementations": list(self.supported_implementations),
        }


@dataclass(frozen=True)
class StepRunnerHealthItem:
    runner_id: str
    step_type: StepType
    status: StepRunnerHealthStatus
    missing_dependencies: list[str] = field(default_factory=list)
    message: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "runner_id": self.runner_id,
            "step_type": self.step_type.value,
            "status": self.status.value,
            "missing_dependencies": list(self.missing_dependencies),
            "message": self.message,
        }


@dataclass(frozen=True)
class StepRunnerRegistryHealth:
    status: StepRunnerHealthStatus
    items: list[StepRunnerHealthItem]

    @property
    def ok(self) -> bool:
        return self.status == StepRunnerHealthStatus.OK

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status.value,
            "ok": self.ok,
            "items": [item.to_dict() for item in self.items],
        }


@dataclass(frozen=True)
class StepRunnerValidationIssue:
    step_id: str
    code: str
    message: str
    runner_id: str | None = None
    details: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class StepRunnerWorkflowValidationResult:
    passed: bool
    errors: list[StepRunnerValidationIssue] = field(default_factory=list)
    warnings: list[StepRunnerValidationIssue] = field(default_factory=list)


class StepRunnerRegistry:
    def __init__(self, available_dependencies: set[str] | None = None) -> None:
        self._runners: list[StepRunner] = []
        self._by_runner_id: dict[str, StepRunner] = {}
        self._legacy_runner_ids_by_step_type: dict[StepType, str] = {}
        self._available_dependencies: set[str] = set(available_dependencies or set())

    @classmethod
    def with_function_runner(cls, runner: StepRunner) -> StepRunnerRegistry:
        registry = cls()
        registry.register(StepType.FUNCTION, runner)
        registry.add_available_dependency("function_registry")
        return registry

    def register(
        self,
        step_type_or_runner: StepType | str | StepRunner,
        runner: StepRunner | None = None,
    ) -> None:
        if runner is None:
            if not _looks_like_runner(step_type_or_runner):
                raise StepRunnerRegistryError("runner is required")
            actual_runner = cast(StepRunner, step_type_or_runner)
            capability = _runner_capability(actual_runner)
            legacy_step_type: StepType | None = None
        else:
            actual_runner = runner
            capability = _ensure_runner_capability(
                runner=actual_runner,
                step_type=StepType(step_type_or_runner),
            )
            legacy_step_type = StepType(step_type_or_runner)

        if capability.runner_id in self._by_runner_id:
            if (
                legacy_step_type is not None
                and self._by_runner_id[capability.runner_id] is actual_runner
            ):
                if legacy_step_type in self._legacy_runner_ids_by_step_type:
                    raise StepRunnerRegistryError(
                        f"step runner is already registered: {legacy_step_type.value}"
                    )
                self._legacy_runner_ids_by_step_type[legacy_step_type] = capability.runner_id
                return
            raise StepRunnerRegistryError(
                f"step runner is already registered: {capability.runner_id}"
            )
        if legacy_step_type is not None and legacy_step_type in self._legacy_runner_ids_by_step_type:
            raise StepRunnerRegistryError(
                f"step runner is already registered: {legacy_step_type.value}"
            )

        self._runners.append(actual_runner)
        self._by_runner_id[capability.runner_id] = actual_runner
        if legacy_step_type is not None:
            self._legacy_runner_ids_by_step_type[legacy_step_type] = capability.runner_id
            self._available_dependencies.update(capability.required_dependencies)

    def register_alias(self, step_type: StepType | str, runner: StepRunner) -> None:
        """Map an additional StepType to an already registered multi-type runner."""

        actual_step_type = StepType(step_type)
        capability = _runner_capability(runner)
        registered_runner = self._by_runner_id.get(capability.runner_id)
        if registered_runner is None:
            raise StepRunnerRegistryError(
                f"runner must be registered before aliasing: {capability.runner_id}"
            )
        if registered_runner is not runner:
            raise StepRunnerRegistryError(
                f"runner_id is already registered for another runner: {capability.runner_id}"
            )
        if actual_step_type in self._legacy_runner_ids_by_step_type:
            raise StepRunnerRegistryError(
                f"step runner is already registered: {actual_step_type.value}"
            )
        if not _runner_can_resolve(
            runner,
            StepSpec(
                step_id="__registry_alias__",
                implementation="__registry_alias__",
                step_type=actual_step_type,
            ),
        ):
            raise StepRunnerRegistryError(
                "runner cannot resolve alias step_type: "
                f"{capability.runner_id} -> {actual_step_type.value}"
            )
        self._legacy_runner_ids_by_step_type[actual_step_type] = capability.runner_id

    def get(self, step_type: StepType | str) -> StepRunner:
        actual_step_type = StepType(step_type)
        runner_id = self._legacy_runner_ids_by_step_type.get(actual_step_type)
        if runner_id is not None:
            return self._by_runner_id[runner_id]
        runners = self.runners_for_step_type(actual_step_type)
        if runners:
            return runners[0]
        raise StepRunnerRegistryError(
            f"step runner is not registered: {actual_step_type.value}"
        )

    def get_by_runner_id(self, runner_id: str) -> StepRunner:
        try:
            return self._by_runner_id[runner_id]
        except KeyError as exc:
            raise StepRunnerRegistryError(f"step runner is not registered: {runner_id}") from exc

    def resolve(
        self,
        step: StepSpec | None = None,
        *,
        step_type: StepType | str | None = None,
        implementation: str | None = None,
    ) -> StepRunner | None:
        actual_step = step
        if actual_step is None:
            if step_type is None:
                raise TypeError("step or step_type is required")
            actual_step = StepSpec(
                step_id="__registry_resolution__",
                implementation=str(implementation or ""),
                step_type=StepType(step_type),
            )
        for runner in self._runners:
            if _runner_can_resolve(runner, actual_step):
                return runner
        return None

    def runners_for_step_type(self, step_type: StepType | str) -> list[StepRunner]:
        actual_step_type = StepType(step_type)
        runners = [
            runner
            for runner in self._runners
            if _runner_capability(runner).step_type == actual_step_type
        ]
        runner_id = self._legacy_runner_ids_by_step_type.get(actual_step_type)
        if runner_id is not None:
            runner = self._by_runner_id[runner_id]
            if runner not in runners:
                runners.append(runner)
        return runners

    def has_step_type(self, step_type: StepType | str) -> bool:
        return bool(self.runners_for_step_type(step_type))

    def is_registered(self, step_type: StepType | str) -> bool:
        return self.has_step_type(step_type)

    def missing_step_types(self, step_types: list[StepType | str]) -> list[StepType]:
        missing = {
            StepType(step_type)
            for step_type in step_types
            if not self.has_step_type(step_type)
        }
        return sorted(missing, key=lambda step_type: step_type.value)

    def registered_step_types(self) -> list[StepType]:
        return sorted(
            {
                *(_runner_capability(runner).step_type for runner in self._runners),
                *self._legacy_runner_ids_by_step_type.keys(),
            },
            key=lambda step_type: step_type.value,
        )

    def describe(self) -> list[StepRunnerDescriptor]:
        descriptors: list[StepRunnerDescriptor] = []
        for runner in self._runners:
            capability = _runner_capability(runner)
            missing = self._missing_dependencies(capability)
            descriptors.append(
                StepRunnerDescriptor(
                    step_type=capability.step_type,
                    runner_id=capability.runner_id,
                    version=capability.version,
                    supports_checkpoint=capability.supports_checkpoint,
                    supports_resume=capability.supports_resume,
                    supports_timeout=capability.supports_timeout,
                    supports_retry=capability.supports_retry,
                    side_effect_level=StepRunnerSideEffectLevel(capability.side_effect_level).value,
                    required_dependencies=list(capability.required_dependencies),
                    available=not missing,
                    missing_dependencies=missing,
                    description=capability.description,
                    supported_implementations=list(capability.supported_implementations),
                )
            )
        return descriptors

    def set_available_dependencies(self, dependencies: set[str]) -> None:
        self._available_dependencies = set(dependencies)

    def add_available_dependency(self, dependency: str) -> None:
        self._available_dependencies.add(dependency)

    def health_check(self) -> StepRunnerRegistryHealth:
        items: list[StepRunnerHealthItem] = []
        for runner in self._runners:
            capability = _runner_capability(runner)
            missing = self._missing_dependencies(capability)
            if missing:
                items.append(
                    StepRunnerHealthItem(
                        runner_id=capability.runner_id,
                        step_type=capability.step_type,
                        status=StepRunnerHealthStatus.ERROR,
                        missing_dependencies=missing,
                        message=(
                            f"Runner {capability.runner_id} missing dependencies: "
                            f"{missing}"
                        ),
                    )
                )
            else:
                items.append(
                    StepRunnerHealthItem(
                        runner_id=capability.runner_id,
                        step_type=capability.step_type,
                        status=StepRunnerHealthStatus.OK,
                    )
                )
        status = (
            StepRunnerHealthStatus.OK
            if all(item.status == StepRunnerHealthStatus.OK for item in items)
            else StepRunnerHealthStatus.ERROR
        )
        return StepRunnerRegistryHealth(status=status, items=items)

    def validate_workflow(
        self,
        workflow: WorkflowSpec,
    ) -> StepRunnerWorkflowValidationResult:
        errors: list[StepRunnerValidationIssue] = []
        warnings: list[StepRunnerValidationIssue] = []

        for step in workflow.steps:
            runner = self.resolve(step)
            if runner is None:
                if self.has_step_type(step.step_type):
                    code = "implementation_not_resolvable"
                    message = (
                        "No runner can resolve step implementation for "
                        f"step_type={step.step_type.value}, "
                        f"implementation={step.implementation}"
                    )
                else:
                    code = "runner_not_found"
                    message = f"No runner registered for step_type={step.step_type.value}"
                errors.append(
                    StepRunnerValidationIssue(
                        step_id=step.step_id,
                        code=code,
                        message=message,
                        details={
                            "step_type": step.step_type.value,
                            "implementation": step.implementation,
                        },
                    )
                )
                continue

            capability = _runner_capability(runner)
            missing = self._missing_dependencies(capability)
            if missing:
                errors.append(
                    StepRunnerValidationIssue(
                        step_id=step.step_id,
                        runner_id=capability.runner_id,
                        code="runner_missing_dependencies",
                        message=(
                            f"Runner {capability.runner_id} is missing dependencies: "
                            f"{missing}"
                        ),
                        details={"missing_dependencies": missing},
                    )
                )
                continue

            for item in _runner_validate_step(runner, step):
                errors.append(
                    StepRunnerValidationIssue(
                        step_id=step.step_id,
                        runner_id=capability.runner_id,
                        code=item.code,
                        message=item.message,
                        details={
                            "field": item.field,
                            **dict(item.details),
                        },
                    )
                )

        return StepRunnerWorkflowValidationResult(
            passed=not errors,
            errors=errors,
            warnings=warnings,
        )

    def _missing_dependencies(self, capability: StepRunnerCapability) -> list[str]:
        return sorted(
            dependency
            for dependency in capability.required_dependencies
            if dependency not in self._available_dependencies
        )


def _looks_like_runner(value: Any) -> bool:
    return hasattr(value, "run")


def _runner_capability(runner: StepRunner) -> StepRunnerCapability:
    capability = getattr(runner, "capability", None)
    if not isinstance(capability, StepRunnerCapability):
        raise StepRunnerRegistryError(
            f"step runner {type(runner).__name__} does not declare capability"
        )
    return capability


def _ensure_runner_capability(
    *,
    runner: StepRunner,
    step_type: StepType,
) -> StepRunnerCapability:
    capability = getattr(runner, "capability", None)
    if isinstance(capability, StepRunnerCapability):
        if capability.step_type != step_type and not _runner_can_resolve(
            runner,
            StepSpec(
                step_id="__registry_registration__",
                implementation="__registry_registration__",
                step_type=step_type,
            ),
        ):
            raise StepRunnerRegistryError(
                "runner capability step_type does not match registration: "
                f"{capability.step_type.value} != {step_type.value}"
            )
        return capability
    capability = StepRunnerCapability(
        step_type=step_type,
        runner_id=f"legacy.{step_type.value}.{type(runner).__name__}",
        version="0.0.0",
        supports_checkpoint=True,
        supports_resume=True,
        supports_timeout=True,
        supports_retry=True,
        side_effect_level=StepRunnerSideEffectLevel.EXTERNAL_WRITE,
        description=f"Legacy runner wrapper for {type(runner).__name__}.",
    )
    setattr(runner, "capability", capability)
    return capability


def _runner_can_resolve(runner: StepRunner, step: StepSpec) -> bool:
    can_resolve = getattr(runner, "can_resolve", None)
    if callable(can_resolve):
        return bool(can_resolve(step))
    return default_runner_can_resolve(_runner_capability(runner), step)


def _runner_validate_step(runner: StepRunner, step: StepSpec) -> list[ValidationErrorItem]:
    validate_step = getattr(runner, "validate_step", None)
    if callable(validate_step):
        raw_items = validate_step(step)
        if isinstance(raw_items, list):
            return [item for item in raw_items if isinstance(item, ValidationErrorItem)]
    return []



