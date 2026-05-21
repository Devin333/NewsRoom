from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime
from typing import Any

from pydantic import Field, model_validator

from business.foundation import BoardType, PrimitiveModel, Signal, SourceType


class RawSignalInput(PrimitiveModel):
    source_type: SourceType
    source_name: str
    board_hint: BoardType | None = None
    raw_payload: dict[str, Any]
    collected_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @model_validator(mode="after")
    def _normalize_collected_at(self) -> "RawSignalInput":
        if self.collected_at.tzinfo is None:
            object.__setattr__(self, "collected_at", self.collected_at.replace(tzinfo=UTC))
        else:
            object.__setattr__(self, "collected_at", self.collected_at.astimezone(UTC))
        return self


class RejectedSignal(PrimitiveModel):
    raw_input: RawSignalInput
    reason: str
    detail: str


class SignalPipelineStats(PrimitiveModel):
    input_count: int = 0
    normalized_count: int = 0
    duplicate_count: int = 0
    rejected_count: int = 0
    by_signal_type: dict[str, int] = Field(default_factory=dict)
    by_source_type: dict[str, int] = Field(default_factory=dict)

    @classmethod
    def from_signals(
        cls,
        signals: list[Signal],
        *,
        input_count: int,
        rejected_count: int = 0,
        duplicate_count: int = 0,
    ) -> "SignalPipelineStats":
        return cls(
            input_count=input_count,
            normalized_count=len(signals),
            duplicate_count=duplicate_count,
            rejected_count=rejected_count,
            by_signal_type=dict(Counter(signal.signal_type.value for signal in signals)),
            by_source_type=dict(Counter(signal.source.source_type.value for signal in signals)),
        )


class SignalNormalizeResult(PrimitiveModel):
    signals: list[Signal] = Field(default_factory=list)
    rejected: list[RejectedSignal] = Field(default_factory=list)
    stats: SignalPipelineStats = Field(default_factory=SignalPipelineStats)
    warnings: list[str] = Field(default_factory=list)


class SignalPipelineError(Exception):
    def __init__(self, message: str, stats: SignalPipelineStats) -> None:
        super().__init__(message)
        self.message = message
        self.stats = stats
