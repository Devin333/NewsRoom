from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from backend.research.document.chunker import PaperDocumentChunker
from backend.research.document.models import PaperChunk
from backend.research.domain.document import ResearchDocument
from backend.research.rag.evaluation.paper_evidence_eval import (
    EvidenceQAPair,
    load_evidence_golden_set,
)
from framework.rag.core import build_chunk_semantic_key, content_fingerprint

GOLDEN_CORPUS_SNAPSHOT_SCHEMA = "newsroom.golden-corpus-snapshot/v1"
GOLDEN_CORPUS_DOCUMENT_CHECKSUM_SCOPE = "research-document-content/v1"
DEFAULT_GOLDEN_CORPUS_SNAPSHOT_PATH = Path("data/eval/golden_corpus_snapshot.json")

_SNAPSHOT_FIELDS = frozenset(
    {
        "schema",
        "golden_set_checksum",
        "source_documents",
        "chunks",
        "snapshot_checksum",
    }
)
_SOURCE_DOCUMENT_FIELDS = frozenset(
    {
        "paper_id",
        "source_hash",
        "document_checksum",
        "document_checksum_scope",
        "source_refs",
    }
)
_LOCAL_DOCUMENT_METADATA_FIELDS = frozenset({"parse_artifact_dir", "parse_artifacts"})


class GoldenCorpusSnapshotError(ValueError):
    """Raised when the committed golden corpus snapshot is incomplete or corrupt."""


@dataclass(frozen=True)
class GoldenCorpusSourceDocument:
    paper_id: str
    source_hash: str
    document_checksum: str
    document_checksum_scope: str
    source_refs: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "paper_id": self.paper_id,
            "source_hash": self.source_hash,
            "document_checksum": self.document_checksum,
            "document_checksum_scope": self.document_checksum_scope,
            "source_refs": list(self.source_refs),
        }


@dataclass(frozen=True)
class GoldenCorpusSnapshot:
    schema: str
    golden_set_checksum: str
    source_documents: tuple[GoldenCorpusSourceDocument, ...]
    chunks: tuple[PaperChunk, ...]
    snapshot_checksum: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "golden_set_checksum": self.golden_set_checksum,
            "source_documents": [item.to_dict() for item in self.source_documents],
            "chunks": [chunk.model_dump(mode="json") for chunk in self.chunks],
            "snapshot_checksum": self.snapshot_checksum,
        }


def build_golden_corpus_snapshot(
    *,
    golden_set_path: str | Path,
    papers_dir: str | Path,
) -> GoldenCorpusSnapshot:
    golden_path = Path(golden_set_path)
    corpus_path = Path(papers_dir)
    pairs = load_evidence_golden_set(golden_path)
    required_chunks = _required_chunk_owners(pairs)
    required_papers = tuple(sorted({pair.paper_id for pair in pairs}))
    source_documents: list[GoldenCorpusSourceDocument] = []
    chunks_by_id: dict[str, PaperChunk] = {}
    chunker = PaperDocumentChunker()

    for paper_id in required_papers:
        document_path = corpus_path / paper_id / "research_document.json"
        if not document_path.is_file():
            raise GoldenCorpusSnapshotError(
                f"missing research document for golden paper {paper_id}: {document_path}"
            )
        document_bytes = document_path.read_bytes()
        document = _load_research_document(document_bytes, document_path)
        if document.paper_id != paper_id:
            raise GoldenCorpusSnapshotError(
                f"research document paper_id mismatch: expected {paper_id}, "
                f"got {document.paper_id}"
            )
        parse_source = str(document.metadata.get("parse_source") or "nougat")
        paper_chunks = chunker.chunk(document, parse_source)  # type: ignore[arg-type]
        for chunk in paper_chunks:
            if chunk.chunk_id not in required_chunks:
                continue
            owner = required_chunks[chunk.chunk_id]
            if chunk.paper_id != owner:
                raise GoldenCorpusSnapshotError(
                    f"gold chunk {chunk.chunk_id} belongs to {chunk.paper_id}, expected {owner}"
                )
            existing = chunks_by_id.get(chunk.chunk_id)
            if existing is not None and existing != chunk:
                raise GoldenCorpusSnapshotError(
                    f"duplicate gold chunk id has different content: {chunk.chunk_id}"
                )
            chunks_by_id[chunk.chunk_id] = chunk
        source_documents.append(
            GoldenCorpusSourceDocument(
                paper_id=paper_id,
                source_hash=document.source_hash,
                document_checksum=_document_content_checksum(document),
                document_checksum_scope=GOLDEN_CORPUS_DOCUMENT_CHECKSUM_SCOPE,
                source_refs=tuple(document.lineage.source_refs),
            )
        )

    missing = sorted(set(required_chunks) - set(chunks_by_id))
    if missing:
        raise GoldenCorpusSnapshotError(
            "gold chunks missing from rebuilt corpus: " + ", ".join(missing)
        )
    payload: dict[str, Any] = {
        "schema": GOLDEN_CORPUS_SNAPSHOT_SCHEMA,
        "golden_set_checksum": _checksum_bytes(golden_path.read_bytes()),
        "source_documents": [item.to_dict() for item in source_documents],
        "chunks": [
            chunks_by_id[chunk_id].model_dump(mode="json")
            for chunk_id in sorted(chunks_by_id)
        ],
    }
    return _snapshot_from_payload(
        {**payload, "snapshot_checksum": _checksum_value(payload)},
        golden_set_path=golden_path,
    )


def load_golden_corpus_snapshot(
    path: str | Path = DEFAULT_GOLDEN_CORPUS_SNAPSHOT_PATH,
    *,
    golden_set_path: str | Path,
) -> GoldenCorpusSnapshot:
    snapshot_path = Path(path)
    try:
        payload = json.loads(snapshot_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise GoldenCorpusSnapshotError(
            f"cannot read golden corpus snapshot {snapshot_path}: {type(exc).__name__}"
        ) from exc
    if not isinstance(payload, Mapping):
        raise GoldenCorpusSnapshotError("golden corpus snapshot must be a JSON object")
    return _snapshot_from_payload(payload, golden_set_path=Path(golden_set_path))


def write_golden_corpus_snapshot(
    snapshot: GoldenCorpusSnapshot,
    path: str | Path = DEFAULT_GOLDEN_CORPUS_SNAPSHOT_PATH,
) -> None:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(snapshot.to_dict(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _snapshot_from_payload(
    value: Mapping[str, Any],
    *,
    golden_set_path: Path,
) -> GoldenCorpusSnapshot:
    unknown = set(value) - _SNAPSHOT_FIELDS
    missing = _SNAPSHOT_FIELDS - set(value)
    if unknown or missing:
        raise GoldenCorpusSnapshotError(
            _field_mismatch("golden corpus snapshot", unknown=unknown, missing=missing)
        )
    schema = _required_text(value["schema"], "schema")
    if schema != GOLDEN_CORPUS_SNAPSHOT_SCHEMA:
        raise GoldenCorpusSnapshotError(
            f"unsupported golden corpus snapshot schema: {schema}"
        )
    golden_set_checksum = _checksum_text(
        value["golden_set_checksum"], "golden_set_checksum"
    )
    try:
        actual_golden_checksum = _checksum_bytes(golden_set_path.read_bytes())
    except OSError as exc:
        raise GoldenCorpusSnapshotError(
            f"cannot read golden set {golden_set_path}: {type(exc).__name__}"
        ) from exc
    if golden_set_checksum != actual_golden_checksum:
        raise GoldenCorpusSnapshotError(
            "golden corpus snapshot does not match the current golden set"
        )

    raw_sources = _array(value["source_documents"], "source_documents")
    source_documents = tuple(_source_document(item) for item in raw_sources)
    source_ids = [item.paper_id for item in source_documents]
    if source_ids != sorted(set(source_ids)):
        raise GoldenCorpusSnapshotError(
            "source_documents must have unique paper_id values in sorted order"
        )

    raw_chunks = _array(value["chunks"], "chunks")
    chunks = tuple(_paper_chunk(item) for item in raw_chunks)
    chunk_ids = [chunk.chunk_id for chunk in chunks]
    if chunk_ids != sorted(set(chunk_ids)):
        raise GoldenCorpusSnapshotError(
            "chunks must have unique chunk_id values in sorted order"
        )
    _validate_chunk_content_hashes(chunks)

    pairs = load_evidence_golden_set(golden_set_path)
    required_chunks = _required_chunk_owners(pairs)
    expected_papers = sorted({pair.paper_id for pair in pairs})
    if source_ids != expected_papers:
        raise GoldenCorpusSnapshotError(
            "source document coverage does not match the current golden set"
        )
    if set(chunk_ids) != set(required_chunks):
        raise GoldenCorpusSnapshotError(
            "chunk coverage does not match the current golden set"
        )
    for chunk in chunks:
        if chunk.paper_id != required_chunks[chunk.chunk_id]:
            raise GoldenCorpusSnapshotError(
                f"gold chunk {chunk.chunk_id} has the wrong paper_id"
            )
    if any(chunk.paper_id not in source_ids for chunk in chunks):
        raise GoldenCorpusSnapshotError("gold chunk has no source document provenance")

    snapshot_checksum = _checksum_text(value["snapshot_checksum"], "snapshot_checksum")
    checksum_payload = {
        key: value[key] for key in sorted(value) if key != "snapshot_checksum"
    }
    if snapshot_checksum != _checksum_value(checksum_payload):
        raise GoldenCorpusSnapshotError("golden corpus snapshot checksum mismatch")
    return GoldenCorpusSnapshot(
        schema=schema,
        golden_set_checksum=golden_set_checksum,
        source_documents=source_documents,
        chunks=chunks,
        snapshot_checksum=snapshot_checksum,
    )


def _source_document(value: Any) -> GoldenCorpusSourceDocument:
    if not isinstance(value, Mapping):
        raise GoldenCorpusSnapshotError("source document provenance must be an object")
    unknown = set(value) - _SOURCE_DOCUMENT_FIELDS
    missing = _SOURCE_DOCUMENT_FIELDS - set(value)
    if unknown or missing:
        raise GoldenCorpusSnapshotError(
            _field_mismatch("source document", unknown=unknown, missing=missing)
        )
    source_refs = tuple(
        _required_text(item, "source_refs item")
        for item in _array(value["source_refs"], "source_refs")
    )
    if not source_refs:
        raise GoldenCorpusSnapshotError("source document must retain source_refs")
    if len(source_refs) != len(set(source_refs)):
        raise GoldenCorpusSnapshotError("source document source_refs must be unique")
    return GoldenCorpusSourceDocument(
        paper_id=_required_text(value["paper_id"], "paper_id"),
        source_hash=_hash_text(value["source_hash"], "source_hash"),
        document_checksum=_checksum_text(
            value["document_checksum"], "document_checksum"
        ),
        document_checksum_scope=_document_checksum_scope(
            value["document_checksum_scope"]
        ),
        source_refs=source_refs,
    )


def _paper_chunk(value: Any) -> PaperChunk:
    if not isinstance(value, Mapping):
        raise GoldenCorpusSnapshotError("snapshot chunk must be an object")
    try:
        return PaperChunk.model_validate(value)
    except Exception as exc:
        raise GoldenCorpusSnapshotError(
            f"invalid snapshot chunk: {type(exc).__name__}"
        ) from exc


def _load_research_document(data: bytes, path: Path) -> ResearchDocument:
    try:
        value = json.loads(data)
        return ResearchDocument.model_validate(value)
    except Exception as exc:
        raise GoldenCorpusSnapshotError(
            f"invalid research document {path}: {type(exc).__name__}"
        ) from exc


def _document_content_checksum(document: ResearchDocument) -> str:
    value = document.model_dump(mode="json")
    metadata = dict(value.get("metadata") or {})
    for field_name in _LOCAL_DOCUMENT_METADATA_FIELDS:
        metadata.pop(field_name, None)
    value["metadata"] = metadata
    return _checksum_value(value)


def _required_chunk_owners(pairs: Sequence[EvidenceQAPair]) -> dict[str, str]:
    owners: dict[str, str] = {}
    for pair in pairs:
        if pair.expected_behavior != "answer":
            continue
        if not pair.gold_chunk_ids:
            raise GoldenCorpusSnapshotError(
                f"answer pair has no gold chunk ids: {pair.question}"
            )
        for chunk_id in pair.gold_chunk_ids:
            existing = owners.setdefault(chunk_id, pair.paper_id)
            if existing != pair.paper_id:
                raise GoldenCorpusSnapshotError(
                    f"gold chunk {chunk_id} is assigned to multiple papers"
                )
    if not owners:
        raise GoldenCorpusSnapshotError("golden set has no answer chunk coverage")
    return owners


def _validate_chunk_content_hashes(chunks: Sequence[PaperChunk]) -> None:
    for chunk in chunks:
        content_hash = str(chunk.metadata.get("content_hash") or "").strip()
        if not content_hash:
            raise GoldenCorpusSnapshotError(
                f"gold chunk {chunk.chunk_id} has no content_hash"
            )
        semantic_content = _semantic_chunk_content(chunk)
        if content_hash != content_fingerprint(semantic_content):
            raise GoldenCorpusSnapshotError(
                f"gold chunk {chunk.chunk_id} content_hash mismatch"
            )
        source_locator = str(chunk.metadata.get("source_locator") or "").strip()
        if not source_locator:
            raise GoldenCorpusSnapshotError(
                f"gold chunk {chunk.chunk_id} has no source_locator"
            )
        semantic_key = build_chunk_semantic_key(
            document_id=chunk.paper_id,
            chunk_type=chunk.chunk_type,
            section_title=chunk.section_title,
            source_locator=source_locator,
            content=semantic_content,
            content_hash=content_hash,
        )
        if chunk.metadata.get("semantic_key") != semantic_key.key:
            raise GoldenCorpusSnapshotError(
                f"gold chunk {chunk.chunk_id} semantic_key mismatch"
            )


def _semantic_chunk_content(chunk: PaperChunk) -> str:
    span = chunk.metadata.get("main_span")
    if span is None:
        return chunk.content
    if not isinstance(span, Mapping):
        raise GoldenCorpusSnapshotError(
            f"gold chunk {chunk.chunk_id} main_span must be an object"
        )
    start = span.get("start")
    end = span.get("end")
    if (
        isinstance(start, bool)
        or not isinstance(start, int)
        or isinstance(end, bool)
        or not isinstance(end, int)
        or start < 0
        or end <= start
        or end > len(chunk.content)
    ):
        raise GoldenCorpusSnapshotError(
            f"gold chunk {chunk.chunk_id} main_span is invalid"
        )
    return chunk.content[start:end]


def _array(value: Any, field_name: str) -> list[Any]:
    if not isinstance(value, list):
        raise GoldenCorpusSnapshotError(f"{field_name} must be an array")
    return value


def _required_text(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise GoldenCorpusSnapshotError(f"{field_name} must be a non-empty string")
    return value.strip()


def _hash_text(value: Any, field_name: str) -> str:
    text = _required_text(value, field_name)
    if len(text) != 64 or any(char not in "0123456789abcdef" for char in text):
        raise GoldenCorpusSnapshotError(
            f"{field_name} must be a lowercase SHA-256 hash"
        )
    return text


def _checksum_text(value: Any, field_name: str) -> str:
    text = _required_text(value, field_name)
    if not text.startswith("sha256:"):
        raise GoldenCorpusSnapshotError(f"{field_name} must use sha256:<hex>")
    _hash_text(text.removeprefix("sha256:"), field_name)
    return text


def _document_checksum_scope(value: Any) -> str:
    scope = _required_text(value, "document_checksum_scope")
    if scope != GOLDEN_CORPUS_DOCUMENT_CHECKSUM_SCOPE:
        raise GoldenCorpusSnapshotError(f"unsupported document_checksum_scope: {scope}")
    return scope


def _checksum_bytes(value: bytes) -> str:
    return f"sha256:{hashlib.sha256(value).hexdigest()}"


def _checksum_value(value: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return _checksum_bytes(encoded)


def _field_mismatch(
    context: str,
    *,
    unknown: set[str],
    missing: set[str],
) -> str:
    details: list[str] = []
    if unknown:
        details.append("unknown=" + ",".join(sorted(unknown)))
    if missing:
        details.append("missing=" + ",".join(sorted(missing)))
    return f"{context} fields do not match schema ({'; '.join(details)})"


__all__ = [
    "DEFAULT_GOLDEN_CORPUS_SNAPSHOT_PATH",
    "GOLDEN_CORPUS_DOCUMENT_CHECKSUM_SCOPE",
    "GOLDEN_CORPUS_SNAPSHOT_SCHEMA",
    "GoldenCorpusSnapshot",
    "GoldenCorpusSnapshotError",
    "GoldenCorpusSourceDocument",
    "build_golden_corpus_snapshot",
    "load_golden_corpus_snapshot",
    "write_golden_corpus_snapshot",
]
