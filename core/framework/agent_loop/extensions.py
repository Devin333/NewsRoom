from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from core.framework.agent_loop.models import AgentAction, AgentSpec


class OutputNormalizer(Protocol):
    def __call__(
        self,
        *,
        agent: AgentSpec,
        output: dict[str, Any],
        inputs: dict[str, Any],
    ) -> dict[str, Any]:
        ...


@dataclass(frozen=True)
class OutputValidationResult:
    missing_output_keys: list[str] = field(default_factory=list)
    schema_errors: list[str] = field(default_factory=list)
    quality_errors: list[str] = field(default_factory=list)
    policy_violations: list[str] = field(default_factory=list)
    block: bool = False
    feedback: str | None = None

    @property
    def has_errors(self) -> bool:
        return bool(
            self.missing_output_keys
            or self.schema_errors
            or self.quality_errors
            or self.policy_violations
        )


class OutputValidator(Protocol):
    def __call__(
        self,
        *,
        agent: AgentSpec,
        action: AgentAction,
        called_tools: list[str],
        inputs: dict[str, Any],
    ) -> OutputValidationResult:
        ...


def identity_output_normalizer(
    *,
    agent: AgentSpec,
    output: dict[str, Any],
    inputs: dict[str, Any],
) -> dict[str, Any]:
    _ = agent, inputs
    return output
