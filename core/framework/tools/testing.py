from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from core.framework.artifacts import ArtifactManager
from core.framework.tools.executor import ToolExecutor
from core.framework.tools.models import ToolCall, ToolObservation, ToolPolicy, ToolStatus
from core.framework.tools.registry import ToolRegistry
from core.framework.tools.telemetry import ToolEvent, ToolMetrics


@dataclass(frozen=True)
class ToolTestCase:
    name: str
    call: ToolCall
    policy: ToolPolicy
    expected_status: ToolStatus = ToolStatus.SUCCEEDED
    require_artifact_refs: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ToolTestReport:
    case_name: str
    passed: bool
    errors: list[str]
    observation: ToolObservation
    events: list[ToolEvent]
    metrics: ToolMetrics

    def to_dict(self) -> dict[str, Any]:
        return {
            "case_name": self.case_name,
            "passed": self.passed,
            "errors": list(self.errors),
            "observation": self.observation.to_dict(),
            "events": [event.to_dict() for event in self.events],
            "metrics": self.metrics.to_dict(),
        }


class ToolTestRunner:
    def __init__(
        self,
        registry: ToolRegistry,
        *,
        artifact_manager: ArtifactManager | None = None,
        run_id: str | None = None,
    ) -> None:
        self._registry = registry
        self._artifact_manager = artifact_manager
        self._run_id = run_id

    def run_case(self, test_case: ToolTestCase) -> ToolTestReport:
        executor = ToolExecutor(
            self._registry,
            artifact_manager=self._artifact_manager,
            run_id=self._run_id,
        )
        observation = executor.execute(test_case.call, test_case.policy)
        errors = _expectation_errors(test_case, observation)
        return ToolTestReport(
            case_name=test_case.name,
            passed=not errors,
            errors=errors,
            observation=observation,
            events=executor.list_events(),
            metrics=executor.metrics,
        )

    def run_cases(self, test_cases: list[ToolTestCase]) -> list[ToolTestReport]:
        return [self.run_case(test_case) for test_case in test_cases]


def _expectation_errors(test_case: ToolTestCase, observation: ToolObservation) -> list[str]:
    errors: list[str] = []
    if observation.status != test_case.expected_status:
        errors.append(
            "expected status "
            f"{test_case.expected_status.value}, got {observation.status.value}"
        )
    if test_case.require_artifact_refs and not observation.result.artifact_refs:
        errors.append("expected at least one artifact ref")
    return errors
