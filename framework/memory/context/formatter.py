from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from framework.memory.models import MemoryReference, MemorySearchResult
from framework.memory.models.reference import legacy_refs_from_references


class MemoryContextFormatter:
    def format_entry(self, result: MemorySearchResult, *, index: int) -> str:
        record = result.record
        confidence = _score_text(record.confidence)
        importance = _score_text(record.importance)
        summary = record.summary or record.content
        refs = _safe_refs_text(record.refs)
        refs_line = f"\n   refs: {refs}" if refs else ""
        return (
            f"{index}. [{record.kind.value} | confidence={confidence} | importance={importance}]\n"
            f"   summary: {summary}\n"
            f"   memory_id: {record.memory_id} | source={result.source} | score={result.score:.3f}"
            f"{refs_line}\n"
            f"   content: {record.content}"
        )

    def wrap(self, entries: list[str]) -> str:
        if not entries:
            return ""
        body = "\n\n".join(entries)
        return f"<memory_context>\nRelevant memories:\n{body}\n</memory_context>"


def _score_text(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{float(value):.2f}"


def _safe_refs_text(refs: Mapping[str, Any] | list[MemoryReference | dict[str, Any]]) -> str:
    if isinstance(refs, list):
        refs = legacy_refs_from_references(refs)
    safe_items = [
        f"{key}={refs[key]}"
        for key in sorted(refs)
        if key in _SAFE_REF_KEYS and refs.get(key) is not None
    ]
    return ", ".join(safe_items)


_SAFE_REF_KEYS = {
    "artifact_id",
    "memory_id",
    "record_id",
    "reference_id",
    "reference_ids",
    "run_id",
    "source_memory_ids",
    "graph_id",
    "graph_version",
    "graph_ref",
    "graph_checksum",
    "node_instance_id",
    "stage_id",
}
