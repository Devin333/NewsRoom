"""Declarative workflow spec validation helpers."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


class WorkflowSpecError(ValueError):
    """Raised when a workflow specification is invalid."""


@dataclass(frozen=True)
class ValidationErrorItem:
    code: str
    message: str
    step_id: str | None = None
    edge_id: str | None = None
    path: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "step_id": self.step_id,
            "edge_id": self.edge_id,
            "path": self.path,
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class ValidationWarningItem:
    code: str
    message: str
    step_id: str | None = None
    edge_id: str | None = None
    path: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "step_id": self.step_id,
            "edge_id": self.edge_id,
            "path": self.path,
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class ValidationResult:
    passed: bool = True
    errors: list[ValidationErrorItem] = field(default_factory=list)
    warnings: list[ValidationWarningItem] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.errors and self.passed:
            object.__setattr__(self, "passed", False)

    @property
    def valid(self) -> bool:
        return not self.errors

    def add_error(
        self,
        code: str,
        message: str,
        *,
        path: str | None = None,
    ) -> "ValidationResult":
        return ValidationResult(
            passed=False,
            errors=[*self.errors, ValidationErrorItem(code=code, message=message, path=path)],
            warnings=list(self.warnings),
        )

    def add_warning(
        self,
        code: str,
        message: str,
        *,
        path: str | None = None,
    ) -> "ValidationResult":
        return ValidationResult(
            passed=self.passed and self.valid,
            errors=list(self.errors),
            warnings=[
                *self.warnings,
                ValidationWarningItem(code=code, message=message, path=path),
            ],
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed and self.valid,
            "valid": self.valid,
            "errors": [error.to_dict() for error in self.errors],
            "warnings": [warning.to_dict() for warning in self.warnings],
        }


class WorkflowSpecValidator:
    def validate(self, workflow: Any) -> ValidationResult:
        return workflow.validation_result()

    def _validate_unique_step_ids(self, workflow: Any) -> list[ValidationErrorItem]:
        step_ids = [step.step_id for step in workflow.steps]
        duplicates = sorted({step_id for step_id in step_ids if step_ids.count(step_id) > 1})
        return [
            ValidationErrorItem(
                code="duplicate_step_ids",
                message=f"duplicate step ids: {', '.join(duplicates)}",
                path="steps",
            )
        ] if duplicates else []

    def _validate_edges(self, workflow: Any) -> list[ValidationErrorItem]:
        step_ids = workflow.step_ids()
        errors: list[ValidationErrorItem] = []
        for edge in workflow.edges:
            if edge.source_step_id not in step_ids:
                errors.append(
                    ValidationErrorItem(
                        code="edge_source_missing",
                        message=f"edge {edge.edge_id} references missing source step {edge.source_step_id}",
                        edge_id=edge.edge_id,
                    )
                )
            if edge.target_step_id not in step_ids:
                errors.append(
                    ValidationErrorItem(
                        code="edge_target_missing",
                        message=f"edge {edge.edge_id} references missing target step {edge.target_step_id}",
                        edge_id=edge.edge_id,
                    )
                )
        return errors

    def _validate_reachability(self, workflow: Any) -> list[ValidationWarningItem]:
        if not workflow.steps:
            return []
        adjacency = _workflow_adjacency(workflow)
        reachable_step_ids = _reachable_step_ids(workflow.start_step_id, adjacency)
        return [
            ValidationWarningItem(
                code="step_unreachable",
                message=f"step is not reachable from start step: {step.step_id}",
                step_id=step.step_id,
            )
            for step in workflow.steps
            if step.step_id not in reachable_step_ids
        ]

    def _validate_policies(self, workflow: Any) -> list[ValidationErrorItem]:
        try:
            workflow.policies.to_dict()
        except WorkflowSpecError as exc:
            return [
                ValidationErrorItem(
                    code="policy_invalid",
                    message=str(exc),
                    path="policies",
                )
            ]
        return []


def _workflow_adjacency(workflow: Any) -> dict[str, set[str]]:
    adjacency = {step.step_id: set() for step in workflow.steps}
    for edge in workflow.edges:
        adjacency.setdefault(edge.source_step_id, set()).add(edge.target_step_id)
    for step in workflow.steps:
        fallback_step_id = step.failure_policy.fallback_step_id
        if fallback_step_id is not None:
            adjacency.setdefault(step.step_id, set()).add(fallback_step_id)
    return adjacency


def _reachable_step_ids(start_step_id: str, adjacency: dict[str, set[str]]) -> set[str]:
    reachable: set[str] = set()
    stack = [start_step_id]
    while stack:
        step_id = stack.pop()
        if step_id in reachable:
            continue
        reachable.add(step_id)
        stack.extend(sorted(adjacency.get(step_id, set()) - reachable, reverse=True))
    return reachable


__all__ = [
    "ValidationErrorItem",
    "ValidationResult",
    "ValidationWarningItem",
    "WorkflowSpecError",
    "WorkflowSpecValidator",
]
