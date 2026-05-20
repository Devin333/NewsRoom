"""Workflow specification registry."""

from __future__ import annotations

from framework.specs.validation import WorkflowSpecError
from framework.specs.workflow import WorkflowSpec


class WorkflowSpecRegistry:
    def __init__(self) -> None:
        self._specs: dict[tuple[str, str], WorkflowSpec] = {}
        self._active_versions: dict[str, str] = {}
        self._deprecated_versions: set[tuple[str, str]] = set()

    def register(self, workflow: WorkflowSpec, *, active: bool = True) -> None:
        workflow.validate()
        key = (workflow.workflow_id, workflow.version)
        if key in self._specs:
            raise WorkflowSpecError(
                f"workflow version is already registered: {workflow.workflow_id}@{workflow.version}"
            )
        self._specs[key] = workflow
        if active:
            self._active_versions[workflow.workflow_id] = workflow.version

    def get(self, workflow_id: str, version: str | None = None) -> WorkflowSpec | None:
        actual_version = version or self._active_versions.get(workflow_id)
        if actual_version is None:
            return None
        return self._specs.get((workflow_id, actual_version))

    def latest(self, workflow_id: str) -> WorkflowSpec:
        return self.require(workflow_id)

    def list_versions(self, workflow_id: str) -> list[str]:
        return sorted(version for registered_id, version in self._specs if registered_id == workflow_id)

    def deprecate(self, workflow_id: str, version: str) -> None:
        self.require(workflow_id, version)
        self._deprecated_versions.add((workflow_id, version))

    def is_deprecated(self, workflow_id: str, version: str) -> bool:
        return (workflow_id, version) in self._deprecated_versions

    def require(self, workflow_id: str, version: str | None = None) -> WorkflowSpec:
        spec = self.get(workflow_id, version)
        if spec is None:
            actual_version = version or self._active_versions.get(workflow_id)
            if actual_version is None:
                raise WorkflowSpecError(f"workflow is not registered: {workflow_id}")
            raise WorkflowSpecError(
                f"workflow version is not registered: {workflow_id}@{actual_version}"
            )
        return spec

    def list(self) -> list[WorkflowSpec]:
        return [
            self._specs[key]
            for key in sorted(self._specs, key=lambda item: (item[0], item[1]))
        ]

    def remove(self, workflow_id: str, version: str | None = None) -> None:
        actual_version = version or self._active_versions.get(workflow_id)
        if actual_version is None:
            return
        self._specs.pop((workflow_id, actual_version), None)
        self._deprecated_versions.discard((workflow_id, actual_version))
        if self._active_versions.get(workflow_id) == actual_version:
            remaining = self.list_versions(workflow_id)
            if remaining:
                self._active_versions[workflow_id] = remaining[-1]
            else:
                self._active_versions.pop(workflow_id, None)

    def clear(self) -> None:
        self._specs.clear()
        self._active_versions.clear()
        self._deprecated_versions.clear()


__all__ = ["WorkflowSpecRegistry"]
