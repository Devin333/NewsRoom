from __future__ import annotations

from typing import Any

from framework.harness.rag.models import EvidenceCandidate

_TENANT_METADATA_KEYS = ("tenant_id", "tenant", "workspace_id")
_TENANT_COLLECTION_KEYS = ("tenant_ids", "allowed_tenant_ids")


def evidence_tenant_ids(candidate: EvidenceCandidate) -> set[str]:
    values = _metadata_tenant_ids(candidate.metadata)
    for ref in (
        candidate.source_ref,
        *candidate.span_refs,
        *candidate.artifact_refs,
        *candidate.lineage,
    ):
        ref_tenant = _tenant_from_ref(ref)
        if ref_tenant:
            values.add(ref_tenant)
    return values


def evidence_visible_to_tenant(
    candidate: EvidenceCandidate,
    *,
    tenant_id: str | None,
) -> bool:
    tenant = str(tenant_id or "").strip()
    candidate_tenants = evidence_tenant_ids(candidate)
    if not tenant:
        return not candidate_tenants
    return not candidate_tenants or tenant in candidate_tenants


def _metadata_tenant_ids(metadata: Any) -> set[str]:
    if not isinstance(metadata, dict):
        return set()
    values: set[str] = set()
    for key in _TENANT_METADATA_KEYS:
        _add_tenant_value(values, metadata.get(key))
    for key in _TENANT_COLLECTION_KEYS:
        _add_tenant_value(values, metadata.get(key))
    nested = metadata.get("metadata")
    if isinstance(nested, dict):
        values.update(_metadata_tenant_ids(nested))
    return values


def _add_tenant_value(values: set[str], raw: Any) -> None:
    if raw is None:
        return
    if isinstance(raw, (list, tuple, set)):
        for item in raw:
            _add_tenant_value(values, item)
        return
    text = str(raw).strip()
    if text:
        values.add(text)


def _tenant_from_ref(ref: object) -> str:
    text = str(ref or "").strip()
    if not text.startswith("tenant://"):
        return ""
    return text.removeprefix("tenant://").split("/", 1)[0].strip()


__all__ = ["evidence_tenant_ids", "evidence_visible_to_tenant"]
