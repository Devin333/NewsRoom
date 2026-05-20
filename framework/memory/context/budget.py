from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class MemoryContextBudget:
    max_tokens: int = 2000

    def __post_init__(self) -> None:
        object.__setattr__(self, "max_tokens", max(1, int(self.max_tokens)))
