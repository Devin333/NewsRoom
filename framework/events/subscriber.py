from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

from framework.events.envelope import EventEnvelope


class EventSubscriber(Protocol):
    subscriber_id: str

    def handle(self, envelope: EventEnvelope) -> None:
        ...


@dataclass
class FunctionEventSubscriber:
    callback: Callable[[EventEnvelope], None]
    subscriber_id: str = "function_subscriber"

    def handle(self, envelope: EventEnvelope) -> None:
        self.callback(envelope)
