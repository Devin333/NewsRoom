from __future__ import annotations

from typing import Protocol, runtime_checkable

from framework.execution_environment.models import (
    ExecutionCapabilityProfile,
    ExecutionOutcome,
    ExecutionRequest,
)


@runtime_checkable
class ExecutionEnvironmentPort(Protocol):
    """Provider boundary for one physically isolated process invocation."""

    @property
    def capabilities(self) -> ExecutionCapabilityProfile: ...

    def execute(self, request: ExecutionRequest) -> ExecutionOutcome: ...


__all__ = ["ExecutionEnvironmentPort"]
