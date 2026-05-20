"""Compatibility bridge for memory storage adapters moved to infrastructure."""

from infrastructure.storage.memory import DEFAULT_MEMORY_COLLECTION, VectorMemoryStoreAdapter

__all__ = [
    "DEFAULT_MEMORY_COLLECTION",
    "VectorMemoryStoreAdapter",
]
