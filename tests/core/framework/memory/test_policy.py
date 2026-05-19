import pytest

from core.framework.memory import MemoryKind, MemoryPolicy, MemoryRecord, MemoryScope


def test_memory_policy_rejects_global_write_without_permission() -> None:
    policy = MemoryPolicy(
        allowed_scopes=[MemoryScope.GLOBAL],
        allowed_kinds=[MemoryKind.SEMANTIC],
        allow_global_write=False,
    )
    record = MemoryRecord(
        content="Global fact",
        kind=MemoryKind.SEMANTIC,
        scope=MemoryScope.GLOBAL,
    )

    with pytest.raises(PermissionError, match="global memory writes"):
        policy.validate_write(record)


def test_memory_policy_requires_refs_when_enabled() -> None:
    policy = MemoryPolicy(
        allowed_scopes=[MemoryScope.WORKFLOW],
        allowed_kinds=[MemoryKind.OBSERVATION],
        require_refs=True,
    )
    record = MemoryRecord(
        content="Step observation",
        kind=MemoryKind.OBSERVATION,
        scope=MemoryScope.WORKFLOW,
    )

    with pytest.raises(ValueError, match="refs are required"):
        policy.validate_write(record)

