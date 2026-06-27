from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any


DEFAULT_DIRECT_CONTEXT_KEYS = (
    "nearby_context_chunk_id",
    "parent_table_chunk_id",
    "source_parent_chunk_id",
)

DEFAULT_REFERENCE_LIST_KEYS = ("referenced_by_chunks",)


@dataclass(frozen=True)
class NearbyContextIds:
    ids: tuple[str, ...]
    by_edge: Mapping[str, tuple[str, ...]]

    def to_dict(self) -> dict[str, Any]:
        return {
            "ids": list(self.ids),
            "by_edge": {key: list(value) for key, value in self.by_edge.items()},
        }


def collect_nearby_context_ids(
    *,
    metadata: Mapping[str, Any],
    parent_id: str = "",
    references: Iterable[str] = (),
    direct_keys: tuple[str, ...] = DEFAULT_DIRECT_CONTEXT_KEYS,
    reference_list_keys: tuple[str, ...] = DEFAULT_REFERENCE_LIST_KEYS,
    include_parent: bool = True,
    include_references: bool = False,
) -> NearbyContextIds:
    by_edge: dict[str, list[str]] = {}

    for key in direct_keys:
        value = str(metadata.get(key) or "")
        if value:
            by_edge.setdefault(key, []).append(value)

    if include_parent and parent_id:
        by_edge.setdefault("parent_chunk_id", []).append(parent_id)

    if include_references:
        for ref in references:
            ref_id = str(ref or "")
            if ref_id:
                by_edge.setdefault("references", []).append(ref_id)

    for key in reference_list_keys:
        raw_refs = metadata.get(key, [])
        if not isinstance(raw_refs, list):
            continue
        for ref in raw_refs:
            if not isinstance(ref, Mapping):
                continue
            ref_id = str(ref.get("chunk_id") or "")
            if ref_id:
                by_edge.setdefault(key, []).append(ref_id)

    normalized_by_edge = {
        edge: tuple(_unique_texts(ids))
        for edge, ids in by_edge.items()
        if _unique_texts(ids)
    }
    return NearbyContextIds(
        ids=tuple(_unique_texts(id_ for ids in normalized_by_edge.values() for id_ in ids)),
        by_edge=normalized_by_edge,
    )


def _unique_texts(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        text = str(value or "").strip()
        if not text or text in seen:
            continue
        out.append(text)
        seen.add(text)
    return out


__all__ = [
    "DEFAULT_DIRECT_CONTEXT_KEYS",
    "DEFAULT_REFERENCE_LIST_KEYS",
    "NearbyContextIds",
    "collect_nearby_context_ids",
]
