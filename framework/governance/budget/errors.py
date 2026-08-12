from __future__ import annotations


class BudgetError(RuntimeError):
    """Base error for canonical cumulative budget failures."""


class BudgetContractError(BudgetError, ValueError):
    """An external value violates the canonical budget contract."""


class BudgetIdentityConflictError(BudgetContractError):
    """An operation or idempotency identity was reused with different content."""


class BudgetStateError(BudgetError):
    """A lifecycle transition is invalid for the current reservation state."""


class BudgetHistoryError(BudgetError):
    """A snapshot or event history cannot be restored deterministically."""


class BudgetEventWriteError(BudgetError):
    """A required durable budget event could not be recorded."""


__all__ = [
    "BudgetContractError",
    "BudgetError",
    "BudgetEventWriteError",
    "BudgetHistoryError",
    "BudgetIdentityConflictError",
    "BudgetStateError",
]
