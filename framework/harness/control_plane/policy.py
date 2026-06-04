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
    halt_on_budget_exceeded: bool = True

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
        if not isinstance(self.halt_on_budget_exceeded, bool):
            raise HarnessValidationError("halt_on_budget_exceeded must be a boolean")

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
            halt_on_budget_exceeded=True,
        )

    def to_dict(self) -> dict[str, int | bool]:
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
            "halt_on_budget_exceeded": self.halt_on_budget_exceeded,
        }


@dataclass(frozen=True)
class HarnessBudgetSnapshot:
    max_turns: int
    turns_used: int
    max_replans: int
    replans_used: int
    max_retries_per_step: int
    max_worker_calls: int
    worker_calls_used: int
    max_evolution_epochs: int
    evolution_epochs_used: int
    max_candidates_per_run: int
    candidates_used: int
    max_patch_operations: int
    patch_operations_used: int
    max_eval_cases: int
    eval_cases_used: int
    max_sandbox_runs: int
    sandbox_runs_used: int
    halt_on_budget_exceeded: bool

    @classmethod
    def from_budget(
        cls,
        budget: HarnessBudget,
        *,
        turns_used: int = 0,
        replans_used: int = 0,
        worker_calls_used: int = 0,
        evolution_epochs_used: int = 0,
        candidates_used: int = 0,
        patch_operations_used: int = 0,
        eval_cases_used: int = 0,
        sandbox_runs_used: int = 0,
    ) -> "HarnessBudgetSnapshot":
        return cls(
            max_turns=budget.max_turns,
            turns_used=turns_used,
            max_replans=budget.max_replans,
            replans_used=replans_used,
            max_retries_per_step=budget.max_retries_per_step,
            max_worker_calls=budget.max_worker_calls,
            worker_calls_used=worker_calls_used,
            max_evolution_epochs=budget.max_evolution_epochs,
            evolution_epochs_used=evolution_epochs_used,
            max_candidates_per_run=budget.max_candidates_per_run,
            candidates_used=candidates_used,
            max_patch_operations=budget.max_patch_operations,
            patch_operations_used=patch_operations_used,
            max_eval_cases=budget.max_eval_cases,
            eval_cases_used=eval_cases_used,
            max_sandbox_runs=budget.max_sandbox_runs,
            sandbox_runs_used=sandbox_runs_used,
            halt_on_budget_exceeded=budget.halt_on_budget_exceeded,
        )

    @property
    def turns_remaining(self) -> int:
        return max(self.max_turns - self.turns_used, 0)

    @property
    def replans_remaining(self) -> int:
        return max(self.max_replans - self.replans_used, 0)

    @property
    def worker_calls_remaining(self) -> int:
        return max(self.max_worker_calls - self.worker_calls_used, 0)

    def to_dict(self) -> dict[str, int | bool]:
        return {
            "max_turns": self.max_turns,
            "turns_used": self.turns_used,
            "turns_remaining": self.turns_remaining,
            "max_replans": self.max_replans,
            "replans_used": self.replans_used,
            "replans_remaining": self.replans_remaining,
            "max_retries_per_step": self.max_retries_per_step,
            "max_worker_calls": self.max_worker_calls,
            "worker_calls_used": self.worker_calls_used,
            "worker_calls_remaining": self.worker_calls_remaining,
            "max_evolution_epochs": self.max_evolution_epochs,
            "evolution_epochs_used": self.evolution_epochs_used,
            "max_candidates_per_run": self.max_candidates_per_run,
            "candidates_used": self.candidates_used,
            "max_patch_operations": self.max_patch_operations,
            "patch_operations_used": self.patch_operations_used,
            "max_eval_cases": self.max_eval_cases,
            "eval_cases_used": self.eval_cases_used,
            "max_sandbox_runs": self.max_sandbox_runs,
            "sandbox_runs_used": self.sandbox_runs_used,
            "halt_on_budget_exceeded": self.halt_on_budget_exceeded,
        }


__all__ = ["HarnessBudget", "HarnessBudgetSnapshot"]
