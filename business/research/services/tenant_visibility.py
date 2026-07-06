from __future__ import annotations

from typing import Any, Iterable

_TENANT_METADATA_KEYS = ("tenant_id", "tenant", "workspace_id")
_TENANT_COLLECTION_KEYS = ("tenant_ids", "allowed_tenant_ids")
_SENSITIVE_PUBLIC_METRIC_KEYS = {
    "allowed_memory_namespace",
    "allowed_memory_namespaces",
    "allowed_namespace",
    "allowed_namespaces",
    "allowed_tenant_ids",
    "memory_namespace",
    "tenant_ids",
    "user",
    "user_id",
    "username",
}


def chunk_visible_to_tenant(chunk: Any, *, tenant_id: str | None) -> bool:
    return metadata_visible_to_tenant(_metadata_for_chunk(chunk), tenant_id=tenant_id)


def payload_visible_to_tenant(payload: dict[str, Any], *, tenant_id: str | None) -> bool:
    return metadata_visible_to_tenant(_metadata_for_payload(payload), tenant_id=tenant_id)


def metadata_visible_to_tenant(metadata: Any, *, tenant_id: str | None) -> bool:
    tenant = str(tenant_id or "").strip()
    if not tenant:
        return True
    chunk_tenants = metadata_tenant_ids(metadata)
    return not chunk_tenants or tenant in chunk_tenants


def metadata_tenant_ids(metadata: Any) -> set[str]:
    if not isinstance(metadata, dict):
        return set()
    values: set[str] = set()
    for key in _TENANT_METADATA_KEYS:
        _add_tenant_value(values, metadata.get(key))
    for key in _TENANT_COLLECTION_KEYS:
        _add_tenant_value(values, metadata.get(key))
    nested = metadata.get("metadata")
    if isinstance(nested, dict):
        values.update(metadata_tenant_ids(nested))
    return values


def public_metrics(metrics: dict[str, Any]) -> dict[str, Any]:
    value = _sanitize_public_metric_value(metrics)
    return value if isinstance(value, dict) else {}


def tenant_id_from_filters(filters: dict[str, Any] | None) -> str | None:
    if not isinstance(filters, dict):
        return None
    for key in _TENANT_METADATA_KEYS:
        raw = filters.get(key)
        if raw is None:
            continue
        text = str(raw).strip()
        if text:
            return text
    return None


def strip_tenant_filters(filters: dict[str, Any] | None) -> tuple[dict[str, Any], str | None]:
    if not isinstance(filters, dict):
        return {}, None
    tenant_id = tenant_id_from_filters(filters)
    storage_filters = {
        key: value
        for key, value in filters.items()
        if key not in {*_TENANT_METADATA_KEYS, *_TENANT_COLLECTION_KEYS}
    }
    return storage_filters, tenant_id


def _metadata_for_chunk(chunk: Any) -> dict[str, Any]:
    metadata = getattr(chunk, "metadata", {})
    if isinstance(metadata, dict):
        return metadata
    return {}


def _metadata_for_payload(payload: dict[str, Any]) -> dict[str, Any]:
    metadata = dict(payload)
    nested = payload.get("metadata")
    if isinstance(nested, dict):
        metadata["metadata"] = nested
    return metadata


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


def _sanitize_public_metric_value(value: Any) -> Any:
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for key, item in value.items():
            key_text = str(key)
            if _sensitive_public_metric_key(key_text):
                continue
            sanitized = _sanitize_public_metric_value(item)
            if sanitized is not None:
                out[key_text] = sanitized
        return out
    if isinstance(value, (list, tuple)):
        return _sanitize_public_metric_sequence(value)
    if isinstance(value, set):
        return _sanitize_public_metric_sequence(sorted(value, key=str))
    if isinstance(value, str) and _sensitive_public_metric_value(value):
        return None
    return value


def _sanitize_public_metric_sequence(values: Iterable[Any]) -> list[Any]:
    out = []
    for item in values:
        sanitized = _sanitize_public_metric_value(item)
        if sanitized is not None:
            out.append(sanitized)
    return out


def _sensitive_public_metric_key(key: str) -> bool:
    normalized = key.casefold()
    if normalized == "tenant_id":
        return False
    if normalized in _SENSITIVE_PUBLIC_METRIC_KEYS:
        return True
    if "memory_namespace" in normalized or "namespace" in normalized:
        return True
    if "user_id" in normalized or normalized.endswith("_user"):
        return True
    return False


def _sensitive_public_metric_value(value: str) -> bool:
    normalized = value.casefold()
    return (
        normalized.startswith("research:tenant:")
        and (":user:" in normalized or normalized.endswith(":public"))
    )


__all__ = [
    "chunk_visible_to_tenant",
    "metadata_tenant_ids",
    "metadata_visible_to_tenant",
    "payload_visible_to_tenant",
    "public_metrics",
    "strip_tenant_filters",
    "tenant_id_from_filters",
]
