from __future__ import annotations

from typing import Any

from domain.sources import SourceDefinition


GOVERNANCE_METADATA_KEYS = (
    "official_source",
    "official_blog",
    "source_kind",
    "kind",
    "category",
)


def source_item_metadata(
    source: SourceDefinition,
    *,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    metadata: dict[str, Any] = {
        "source_reliability": source.reliability.value,
        "source_authority_score": source.authority_score,
    }
    if source.source_type.value == "official_blog":
        metadata.setdefault("official_blog", True)
        metadata.setdefault("source_kind", "official_blog")
    elif source.source_type.value == "web_page":
        metadata.setdefault("source_kind", "web_page")
    for key in GOVERNANCE_METADATA_KEYS:
        if key in source.metadata:
            metadata[key] = source.metadata[key]
    if extra:
        metadata.update(extra)
    return metadata
