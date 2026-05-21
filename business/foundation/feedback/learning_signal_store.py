from __future__ import annotations

from business.foundation.models import BusinessLearningSignal


class InMemoryLearningSignalStore:
    def __init__(self) -> None:
        self._signals: dict[str, BusinessLearningSignal] = {}

    def save(self, signals: list[BusinessLearningSignal]) -> None:
        for signal in signals:
            self._signals[signal.signal_id] = signal

    def list(self) -> list[BusinessLearningSignal]:
        return list(self._signals.values())
