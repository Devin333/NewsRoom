from __future__ import annotations

from dataclasses import dataclass

from framework.harness.control_plane.errors import HarnessValidationError


@dataclass(frozen=True)
class HarnessBudget:
    max_turns: int
    max_replans: int
    max_retries_per_step: int
    max_worker_calls: int
    max_evolution_epochs: int = 0
    max_candidates_per_run: int = 0
    max_patch_operations: int = 0
    max_eval_cases: int = 0
    max_sandbox_runs: int = 0

    def __post_init__(self) -> None:
        for name in (
            "max_turns",
            "max_replans",
            "max_retries_per_step",
            "max_worker_calls",
            "max_evolution_epochs",
            "max_candidates_per_run",
            "max_patch_operations",
            "max_eval_cases",
            "max_sandbox_runs",
        ):
            value = getattr(self, name)
            if not isinstance(value, int):
                raise HarnessValidationError(f"{name} must be an integer")
            if name in {"max_turns", "max_worker_calls"} and value <= 0:
                raise HarnessValidationError(f"{name} must be greater than zero")
            if name not in {"max_turns", "max_worker_calls"} and value < 0:
                raise HarnessValidationError(f"{name} must not be negative")

    @classmethod
    def safe_default(cls) -> "HarnessBudget":
        return cls(
            max_turns=12,
            max_replans=2,
            max_retries_per_step=2,
            max_worker_calls=24,
            max_evolution_epochs=0,
            max_candidates_per_run=0,
            max_patch_operations=0,
            max_eval_cases=0,
            max_sandbox_runs=0,
        )

    def to_dict(self) -> dict[str, int]:
        return {
            "max_turns": self.max_turns,
            "max_replans": self.max_replans,
            "max_retries_per_step": self.max_retries_per_step,
            "max_worker_calls": self.max_worker_calls,
            "max_evolution_epochs": self.max_evolution_epochs,
            "max_candidates_per_run": self.max_candidates_per_run,
            "max_patch_operations": self.max_patch_operations,
            "max_eval_cases": self.max_eval_cases,
            "max_sandbox_runs": self.max_sandbox_runs,
        }


__all__ = ["HarnessBudget"]
