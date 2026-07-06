from __future__ import annotations

from dataclasses import dataclass, field

from business.research.services.tenant_visibility import chunk_visible_to_tenant, public_metrics


@dataclass
class _Chunk:
    metadata: dict = field(default_factory=dict)


def test_chunk_visibility_allows_public_and_same_tenant_chunks() -> None:
    assert chunk_visible_to_tenant(_Chunk(), tenant_id="tenant-a") is True
    assert chunk_visible_to_tenant(_Chunk({"tenant_id": "tenant-a"}), tenant_id="tenant-a") is True
    assert chunk_visible_to_tenant(_Chunk({"allowed_tenant_ids": ["tenant-a"]}), tenant_id="tenant-a") is True


def test_chunk_visibility_rejects_other_tenant_chunks() -> None:
    assert chunk_visible_to_tenant(_Chunk({"tenant_id": "tenant-b"}), tenant_id="tenant-a") is False


def test_public_metrics_removes_user_and_namespace_scope_recursively() -> None:
    metrics = public_metrics({
        "tenant_id": "tenant-a",
        "user_id": "user-1",
        "memory_namespace": "research:tenant:tenant-a:user:user-1",
        "nested": {
            "allowed_memory_namespaces": ["research:tenant:tenant-a:user:user-1"],
            "safe_count": 2,
        },
    })

    assert metrics == {
        "tenant_id": "tenant-a",
        "nested": {"safe_count": 2},
    }
