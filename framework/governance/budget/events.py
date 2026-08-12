from __future__ import annotations

from typing import Protocol, runtime_checkable

from framework.governance.budget.errors import BudgetEventWriteError
from framework.governance.budget.models import BudgetEvent


@runtime_checkable
class BudgetEventSink(Protocol):
    required: bool

    def append(self, event: BudgetEvent) -> None: ...


class InMemoryBudgetEventSink:
    """Explicit test/development sink; production adapters use framework.events."""

    required = True

    def __init__(self) -> None:
        self._events: list[BudgetEvent] = []

    def append(self, event: BudgetEvent) -> None:
        if not isinstance(event, BudgetEvent):
            raise BudgetEventWriteError("budget event sink accepts BudgetEvent only")
        self._events.append(event)

    def events(self) -> tuple[BudgetEvent, ...]:
        return tuple(self._events)


__all__ = ["BudgetEventSink", "InMemoryBudgetEventSink"]
