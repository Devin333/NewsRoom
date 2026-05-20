from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class MemoryForgettingPolicy:
    allow_hard_delete: bool = True
    default_reason: str = "forgotten by policy"
