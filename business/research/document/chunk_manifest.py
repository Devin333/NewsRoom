from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from business.research.document.models import PaperChunk
from business.research.document.citation_spans import remap_span_origin_ids
from framework.rag.core import build_chunk_semantic_key, build_rag_stable_id, content_fingerprint


_MANIFEST_VERSION = 1


def default_chunk_manifest_path(paper_id: str) -> Path:
    root = Path(os.environ.get("NEWS_ARTIFACT_ROOT", ".newsroom/runs"))
    return root.parent / "papers" / paper_id / "chunk_manifest.json"


class ChunkManifestManager:
    def __init__(self, manifest_path: str | Path | None = None) -> None:
        self._manifest_path = Path(manifest_path) if manifest_path is not None else None

    def path_for(self, paper_id: str) -> Path:
        return self._manifest_path or default_chunk_manifest_path(paper_id)

    def resolve_chunk_ids(self, paper_id: str, chunks: list[PaperChunk]) -> list[PaperChunk]:
        if not chunks:
            return []
        manifest = self._load(paper_id)
        previous_by_key = _previous_chunk_ids_by_semantic_key(manifest)
        previous_ids = set(previous_by_key.values())
        keyed_chunks = _ensure_unique_semantic_keys(paper_id, chunks)
        old_id_counts: dict[str, int] = {}
        for chunk in keyed_chunks:
            old_id_counts[chunk.chunk_id] = old_id_counts.get(chunk.chunk_id, 0) + 1

        id_map: dict[str, str] = {}
        resolved_pairs: list[tuple[PaperChunk, str]] = []
        used_ids: set[str] = set()
        for chunk in keyed_chunks:
            semantic_key = str(chunk.metadata.get("semantic_key") or "")
            old_id = chunk.chunk_id
            resolved_id = previous_by_key.get(semantic_key)
            if resolved_id is None:
                resolved_id = (
                    build_rag_stable_id("chunk", paper_id, "new", semantic_key)
                    if old_id in previous_ids
                    else old_id
                )
            if resolved_id in used_ids:
                if old_id not in used_ids and old_id not in previous_ids:
                    resolved_id = old_id
                else:
                    resolved_id = build_rag_stable_id(
                        "chunk",
                        paper_id,
                        "manifest",
                        semantic_key,
                        old_id,
                    )
                    collision_index = 2
                    while resolved_id in used_ids:
                        resolved_id = build_rag_stable_id(
                            "chunk",
                            paper_id,
                            "manifest",
                            semantic_key,
                            old_id,
                            str(collision_index),
                        )
                        collision_index += 1
            if old_id_counts.get(old_id, 0) == 1:
                id_map[old_id] = resolved_id
            resolved_pairs.append((chunk, resolved_id))
            used_ids.add(resolved_id)

        return [
            _remap_chunk_identity(chunk, resolved_id, id_map)
            for chunk, resolved_id in resolved_pairs
        ]

    def write(
        self,
        paper_id: str,
        chunks: list[PaperChunk],
        *,
        document_metadata: dict[str, Any] | None = None,
    ) -> Path:
        path = self.path_for(paper_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        previous = self._load(paper_id)
        current_keys = {
            str(chunk.metadata.get("semantic_key"))
            for chunk in chunks
            if chunk.metadata.get("semantic_key")
        }
        stale_chunk_ids = [
            str(entry.get("chunk_id"))
            for entry in previous.get("chunks", [])
            if entry.get("semantic_key") and entry.get("semantic_key") not in current_keys
        ]
        payload = {
            "version": _MANIFEST_VERSION,
            "paper_id": paper_id,
            "chunks": [_manifest_entry(chunk) for chunk in chunks],
            "stale_chunk_ids": stale_chunk_ids,
            **_parser_cascade_manifest(document_metadata),
        }
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        return path

    def _load(self, paper_id: str) -> dict[str, Any]:
        path = self.path_for(paper_id)
        if not path.exists():
            return {"version": _MANIFEST_VERSION, "paper_id": paper_id, "chunks": []}
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {"version": _MANIFEST_VERSION, "paper_id": paper_id, "chunks": []}
        if not isinstance(payload, dict):
            return {"version": _MANIFEST_VERSION, "paper_id": paper_id, "chunks": []}
        chunks = payload.get("chunks")
        if not isinstance(chunks, list):
            payload["chunks"] = []
        return payload


def _previous_chunk_ids_by_semantic_key(manifest: dict[str, Any]) -> dict[str, str]:
    result: dict[str, str] = {}
    for entry in manifest.get("chunks", []):
        if not isinstance(entry, dict):
            continue
        semantic_key = entry.get("semantic_key")
        chunk_id = entry.get("chunk_id")
        if semantic_key and chunk_id and semantic_key not in result:
            result[str(semantic_key)] = str(chunk_id)
    return result


def _ensure_unique_semantic_keys(paper_id: str, chunks: list[PaperChunk]) -> list[PaperChunk]:
    by_id = {chunk.chunk_id: chunk for chunk in chunks}
    counts: dict[str, int] = {}
    keyed: list[PaperChunk] = []
    for chunk in chunks:
        metadata = _ensure_semantic_metadata(paper_id, chunk, by_id)
        base_key = str(metadata["semantic_key"])
        occurrence = counts.get(base_key, 0) + 1
        counts[base_key] = occurrence
        if occurrence > 1:
            metadata["semantic_key_base"] = base_key
            metadata["semantic_key_occurrence"] = occurrence
            metadata["semantic_key"] = f"{base_key}#{occurrence}"
        else:
            metadata["semantic_key_occurrence"] = occurrence
        keyed.append(chunk.model_copy(update={"metadata": metadata}))
    return keyed


def _ensure_semantic_metadata(
    paper_id: str,
    chunk: PaperChunk,
    chunks_by_id: dict[str, PaperChunk],
) -> dict[str, Any]:
    metadata = dict(chunk.metadata)
    parent = chunks_by_id.get(chunk.parent_chunk_id or "")
    source_chunk = chunks_by_id.get(str(metadata.get("source_chunk_id") or ""))
    anchor = parent or source_chunk
    source_ref = str(
        metadata.get("source_ref")
        or (anchor.metadata.get("source_ref") if anchor else "")
        or f"paper://{paper_id}"
    )
    source_locator = str(
        metadata.get("source_locator")
        or (anchor.metadata.get("source_locator") if anchor else "")
        or source_ref
    )
    content_hash = str(metadata.get("content_hash") or content_fingerprint(chunk.content))
    semantic_key = metadata.get("semantic_key")
    if not semantic_key:
        semantic = build_chunk_semantic_key(
            document_id=paper_id,
            chunk_type=chunk.chunk_type,
            section_title=chunk.section_title or (anchor.section_title if anchor else ""),
            source_locator=source_locator,
            content=chunk.content,
            content_hash=content_hash,
        )
        semantic_key = semantic.key
        content_hash = semantic.content_hash
        metadata["semantic_key_parts"] = dict(semantic.parts)
    metadata["source_ref"] = source_ref
    metadata["source_locator"] = source_locator
    metadata["content_hash"] = content_hash
    metadata["semantic_key"] = str(semantic_key)
    return metadata


def _remap_chunk_identity(
    chunk: PaperChunk,
    resolved_id: str,
    id_map: dict[str, str],
) -> PaperChunk:
    metadata = dict(chunk.metadata)
    metadata = remap_span_origin_ids(metadata, id_map)
    updates: dict[str, Any] = {}
    if resolved_id != chunk.chunk_id:
        metadata["generated_chunk_id"] = chunk.chunk_id
        metadata["chunk_id_reused_from_manifest"] = True
        updates["chunk_id"] = resolved_id
    else:
        metadata.setdefault("chunk_id_reused_from_manifest", False)

    if chunk.parent_chunk_id and chunk.parent_chunk_id in id_map:
        updates["parent_chunk_id"] = id_map[chunk.parent_chunk_id]

    source_chunk_id = metadata.get("source_chunk_id")
    if source_chunk_id is not None:
        source_chunk_id_text = str(source_chunk_id)
        if source_chunk_id_text in id_map:
            metadata["source_chunk_id"] = id_map[source_chunk_id_text]

    remapped_refs = [id_map.get(ref, ref) for ref in chunk.references]
    if remapped_refs != chunk.references:
        updates["references"] = remapped_refs

    updates["metadata"] = metadata
    return chunk.model_copy(update=updates)


def _manifest_entry(chunk: PaperChunk) -> dict[str, Any]:
    return {
        "chunk_id": chunk.chunk_id,
        "semantic_key": chunk.metadata.get("semantic_key"),
        "content_hash": chunk.metadata.get("content_hash"),
        "chunk_type": chunk.chunk_type,
        "parent_chunk_id": chunk.parent_chunk_id,
        "section_title": chunk.section_title,
        "section_index": chunk.section_index,
        "source_locator": chunk.metadata.get("source_locator"),
        "source_ref": chunk.metadata.get("source_ref"),
    }


def _parser_cascade_manifest(document_metadata: dict[str, Any] | None) -> dict[str, Any]:
    if not document_metadata:
        return {}
    cascade = document_metadata.get("parser_cascade")
    if not isinstance(cascade, dict):
        return {}
    return {"parser_cascade": cascade}


__all__ = ["ChunkManifestManager", "default_chunk_manifest_path"]
