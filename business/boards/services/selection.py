from __future__ import annotations

from typing import Any

from business.foundation import AnalysisContext, BoardDefinition, BoardType, Signal
from business.layers.signal import SignalPipeline


class BoardSignalSelectionService:
    def __init__(
        self,
        *,
        board_type: BoardType,
        board_definition: BoardDefinition,
        signal_pipeline: SignalPipeline | None = None,
    ) -> None:
        self.board_type = board_type
        self.board_definition = board_definition
        self.signal_pipeline = signal_pipeline or SignalPipeline()

    def select(self, signals: list[Any], *, context: AnalysisContext) -> list[Signal]:
        coerced = self.signal_pipeline.coerce_signals(
            list(signals),
            context=context,
            board_type=self.board_type,
        ).signals
        if self.board_type == BoardType.CROSS_BOARD:
            return sorted(coerced, key=_signal_sort_key, reverse=True)
        selected = [
            signal
            for signal in coerced
            if signal.board_type == self.board_type
            or signal.signal_type.value in self.board_definition.signal_types
        ]
        return sorted(selected, key=_signal_sort_key, reverse=True)


def _signal_sort_key(signal: Signal) -> tuple[int, str, str]:
    published_at = signal.published_at
    timestamp = int(published_at.timestamp()) if published_at is not None else 0
    return timestamp, signal.signal_id, signal.title


__all__ = ["BoardSignalSelectionService"]
