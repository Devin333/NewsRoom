from __future__ import annotations

import core.framework.memory as legacy
import framework.memory as canonical


def test_core_framework_memory_reexports_canonical_api() -> None:
    assert legacy.MemoryRuntime is canonical.MemoryRuntime
    assert legacy.MemoryRecord is canonical.MemoryRecord
    assert legacy.MemoryQuery is canonical.MemoryQuery
    assert legacy.InMemoryMemoryStore is canonical.InMemoryMemoryStore
    assert legacy.MemoryPolicy is canonical.MemoryPolicy
