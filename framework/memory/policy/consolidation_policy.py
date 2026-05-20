from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class MemoryConsolidationPolicy:
    invalidate_sources_after_consolidation: bool = False
    min_source_count: int = 1
