from __future__ import annotations

from typing import Any

from framework.workflow.routing.engine import _evaluate_condition


class ConditionEvaluator:
    def evaluate(self, expression: str, context: dict[str, Any]) -> bool:
        return _evaluate_condition(expression, context)


