from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from framework.specs import EdgeSpec
from framework.workflow.buffer import DataBuffer
from framework.workflow.runtime.result import StepOutcome


RoutingPredicate = Callable[["RoutingPredicateContext"], bool]


@dataclass(frozen=True)
class RoutingPredicateContext:
    edge: EdgeSpec
    outcome: StepOutcome
    buffer: DataBuffer | None = None


class RoutingPredicateRegistry:
    def __init__(self, predicates: dict[str, RoutingPredicate] | None = None) -> None:
        self._predicates: dict[str, RoutingPredicate] = dict(predicates or {})

    def register(self, condition: str, predicate: RoutingPredicate) -> None:
        if not condition:
            raise ValueError("condition is required")
        self._predicates[str(condition)] = predicate

    def get(self, condition: str) -> RoutingPredicate | None:
        return self._predicates.get(str(condition))

    def merge(self, other: RoutingPredicateRegistry | None) -> RoutingPredicateRegistry:
        merged = RoutingPredicateRegistry(self._predicates)
        if other is not None:
            merged._predicates.update(other._predicates)
        return merged


def lookup_buffer(buffer: DataBuffer | None, key: str) -> Any:
    if buffer is None or not buffer.exists(key):
        return None
    return buffer.read(key)


def lookup(value: Any, key: str) -> Any:
    if isinstance(value, dict):
        return value.get(key)
    if hasattr(value, key):
        return getattr(value, key)
    return None
