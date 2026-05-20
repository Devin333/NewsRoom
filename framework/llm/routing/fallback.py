from __future__ import annotations

from dataclasses import dataclass

from framework.llm.routing.deployment import ModelDeployment


@dataclass(frozen=True)
class LLMFallbackPolicy:
    skip_disabled: bool = True

    def next_deployment(
        self,
        failed: ModelDeployment,
        candidates: list[ModelDeployment],
    ) -> ModelDeployment | None:
        for candidate in candidates:
            if candidate.deployment_id == failed.deployment_id:
                continue
            if self.skip_disabled and not candidate.enabled:
                continue
            return candidate
        return None


__all__ = ["LLMFallbackPolicy"]
