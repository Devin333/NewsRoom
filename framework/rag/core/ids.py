from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha1, sha256
import re
from typing import Any, Mapping


@dataclass(frozen=True)
class RAGSemanticKey:
    key: str
    content_hash: str
    parts: Mapping[str, str]


def build_rag_stable_id(prefix: str, *parts: Any, length: int = 12) -> str:
    normalized = "|".join(_normalize_part(part) for part in parts)
    digest = sha1(normalized.encode("utf-8")).hexdigest()[:length]
    clean_prefix = normalize_rag_key(prefix) or "rag"
    return f"{clean_prefix}_{digest}"


def normalize_rag_key(text: str) -> str:
    value = str(text).strip().casefold()
    value = value.replace("&", " and ")
    value = "".join(ch if ch.isalnum() else "_" for ch in value)
    while "__" in value:
        value = value.replace("__", "_")
    return value.strip("_")


def normalize_semantic_text(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "").casefold()).strip()


def content_fingerprint(text: str, *, length: int = 16) -> str:
    normalized = normalize_semantic_text(text)
    return sha256(normalized.encode("utf-8")).hexdigest()[:length]


def build_chunk_semantic_key(
    *,
    document_id: str,
    chunk_type: str,
    section_title: str,
    source_locator: str,
    content: str,
    content_hash: str | None = None,
) -> RAGSemanticKey:
    title_key = normalize_semantic_text(section_title)
    resolved_content_hash = str(content_hash or "").strip() or content_fingerprint(content)
    parts = {
        "chunk_type": str(chunk_type),
        "section_title": title_key,
        "source_locator": str(source_locator or ""),
        "content_hash": resolved_content_hash,
    }
    return RAGSemanticKey(
        key=build_rag_stable_id(
            "chunk_semantic",
            document_id,
            chunk_type,
            title_key,
            source_locator,
            resolved_content_hash,
        ),
        content_hash=resolved_content_hash,
        parts=parts,
    )


def _normalize_part(part: Any) -> str:
    if isinstance(part, dict):
        return repr(sorted((str(key), _normalize_part(value)) for key, value in part.items()))
    if isinstance(part, (list, tuple, set)):
        return repr([_normalize_part(value) for value in part])
    if hasattr(part, "model_dump"):
        return repr(part.model_dump(mode="json", exclude_none=True))
    return str(part).strip().casefold()


__all__ = [
    "RAGSemanticKey",
    "build_chunk_semantic_key",
    "build_rag_stable_id",
    "content_fingerprint",
    "normalize_rag_key",
    "normalize_semantic_text",
]
