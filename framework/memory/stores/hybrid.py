from __future__ import annotations

from typing import Protocol

from framework.memory.stores.base import MemoryStore


class HybridMemoryStore(MemoryStore, Protocol):
    pass

__all__ = ["HybridMemoryStore"]
