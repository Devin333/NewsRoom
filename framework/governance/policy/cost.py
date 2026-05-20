from __future__ import annotations

from dataclasses import dataclass

from framework.shared.errors import ValidationError


@dataclass
class CostPolicy:
    limit: float | None = None
    spent: float = 0.0

    def __post_init__(self) -> None:
        if self.limit is not None and self.limit < 0:
            raise ValidationError("cost limit must be non-negative", code="invalid_cost_limit")
        if self.spent < 0:
            raise ValidationError("spent cost must be non-negative", code="invalid_spent_cost")

    def can_spend(self, amount: float) -> bool:
        actual = _non_negative_amount(amount)
        if self.limit is None:
            return True
        return self.spent + actual <= self.limit

    def record(self, amount: float) -> None:
        self.spent += _non_negative_amount(amount)

    def remaining(self) -> float | None:
        if self.limit is None:
            return None
        return max(0.0, self.limit - self.spent)


def _non_negative_amount(amount: float) -> float:
    actual = float(amount)
    if actual < 0:
        raise ValidationError("cost amount must be non-negative", code="invalid_cost_amount")
    return actual
