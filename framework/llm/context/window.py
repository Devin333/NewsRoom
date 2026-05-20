from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


ContextStrategy = Literal["fail", "require_compaction", "truncate_oldest_messages", "summarize_then_retry"]


@dataclass(frozen=True)
class ContextPolicy:
    max_context_tokens: int
    reserve_output_tokens: int = 0
    truncate_strategy: ContextStrategy = "require_compaction"

    def __post_init__(self) -> None:
        if self.max_context_tokens < 1:
            raise ValueError("max_context_tokens must be at least 1")
        if self.reserve_output_tokens < 0:
            raise ValueError("reserve_output_tokens must be non-negative")

