from __future__ import annotations

from typing import Protocol, runtime_checkable

from backend.foundation.context import AnalysisContext
from backend.foundation.models import Signal
from backend.foundation.taxonomy import SignalType


@runtime_checkable
class SourcePort(Protocol):
    def fetch(self, signal_type: SignalType, *, limit: int, context: AnalysisContext) -> list[Signal]: ...


__all__ = ["SourcePort"]
