from __future__ import annotations

import json
import math
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from business.research.document.models import PaperChunk

_VERSION = 1
_TOKEN_RE = re.compile(r"[A-Za-z0-9_]+|[\u4e00-\u9fff]")


@dataclass(frozen=True)
class BM25Hit:
    chunk: PaperChunk
    score: float


class PaperBM25Index:
    def __init__(
        self,
        *,
        paper_id: str,
        chunks: list[PaperChunk],
        tokenized_docs: list[list[str]],
        doc_freqs: dict[str, int],
        postings: dict[str, dict[int, int]],
        avg_doc_len: float,
        k1: float = 1.5,
        b: float = 0.75,
    ) -> None:
        self.paper_id = paper_id
        self.chunks = chunks
        self.tokenized_docs = tokenized_docs
        self.doc_freqs = doc_freqs
        self.postings = postings
        self.avg_doc_len = avg_doc_len
        self.k1 = k1
        self.b = b

    @classmethod
    def build(cls, paper_id: str, chunks: list[PaperChunk]) -> "PaperBM25Index":
        scoped = [chunk for chunk in chunks if chunk.paper_id == paper_id]
        tokenized_docs = [_tokenize(_chunk_index_text(chunk)) for chunk in scoped]
        doc_freqs: dict[str, int] = {}
        postings: dict[str, dict[int, int]] = {}
        for doc_index, tokens in enumerate(tokenized_docs):
            term_freqs: dict[str, int] = {}
            for token in tokens:
                term_freqs[token] = term_freqs.get(token, 0) + 1
            for token, freq in term_freqs.items():
                doc_freqs[token] = doc_freqs.get(token, 0) + 1
                postings.setdefault(token, {})[doc_index] = freq
        avg_doc_len = (
            sum(len(tokens) for tokens in tokenized_docs) / len(tokenized_docs)
            if tokenized_docs
            else 0.0
        )
        return cls(
            paper_id=paper_id,
            chunks=scoped,
            tokenized_docs=tokenized_docs,
            doc_freqs=doc_freqs,
            postings=postings,
            avg_doc_len=avg_doc_len,
        )

    def search(self, query: str, *, limit: int) -> list[BM25Hit]:
        query_tokens = _tokenize(query)
        if not query_tokens or not self.chunks:
            return []
        candidate_doc_indexes = sorted({
            doc_index
            for token in set(query_tokens)
            for doc_index in self.postings.get(token, {})
        })
        scored: list[BM25Hit] = []
        for doc_index in candidate_doc_indexes:
            score = self._score(query_tokens, doc_index)
            if score > 0:
                scored.append(BM25Hit(chunk=self.chunks[doc_index], score=round(score, 6)))
        scored.sort(key=lambda item: (-item.score, item.chunk.section_index, item.chunk.chunk_id))
        return scored[:limit]

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": _VERSION,
            "paper_id": self.paper_id,
            "k1": self.k1,
            "b": self.b,
            "avg_doc_len": self.avg_doc_len,
            "doc_freqs": self.doc_freqs,
            "postings": self.postings,
            "chunks": [chunk.model_dump(mode="json") for chunk in self.chunks],
            "tokenized_docs": self.tokenized_docs,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "PaperBM25Index":
        if int(payload.get("version") or 0) != _VERSION:
            raise ValueError("unsupported BM25 index version")
        chunks = [PaperChunk.model_validate(item) for item in payload.get("chunks") or []]
        tokenized_docs = [
            [str(token) for token in tokens]
            for tokens in (payload.get("tokenized_docs") or [])
            if isinstance(tokens, list)
        ]
        if len(tokenized_docs) != len(chunks):
            raise ValueError("BM25 tokenized docs do not match chunks")
        postings = _coerce_postings(payload.get("postings"))
        if not postings:
            postings = _postings_from_tokenized_docs(tokenized_docs)
        return cls(
            paper_id=str(payload["paper_id"]),
            chunks=chunks,
            tokenized_docs=tokenized_docs,
            doc_freqs={str(k): int(v) for k, v in (payload.get("doc_freqs") or {}).items()},
            postings=postings,
            avg_doc_len=float(payload.get("avg_doc_len") or 0.0),
            k1=float(payload.get("k1") or 1.5),
            b=float(payload.get("b") or 0.75),
        )

    def _score(self, query_tokens: list[str], doc_index: int) -> float:
        doc_tokens = self.tokenized_docs[doc_index]
        if not doc_tokens:
            return 0.0
        n_docs = len(self.tokenized_docs)
        doc_len = len(doc_tokens)
        total = 0.0
        for token in query_tokens:
            tf = self.postings.get(token, {}).get(doc_index, 0)
            if tf <= 0:
                continue
            df = self.doc_freqs.get(token, 0)
            idf = math.log(1.0 + (n_docs - df + 0.5) / (df + 0.5))
            denom = tf + self.k1 * (1.0 - self.b + self.b * doc_len / max(self.avg_doc_len, 1e-9))
            total += idf * ((tf * (self.k1 + 1.0)) / denom)
        return total


def default_bm25_index_path(paper_id: str) -> Path:
    root = Path(os.environ.get("NEWS_ARTIFACT_ROOT", ".newsroom/runs"))
    return root.parent / "papers" / paper_id / "bm25_index.json"


def write_bm25_index(paper_id: str, chunks: list[PaperChunk], path: Path | None = None) -> Path:
    target = path or default_bm25_index_path(paper_id)
    target.parent.mkdir(parents=True, exist_ok=True)
    index = PaperBM25Index.build(paper_id, chunks)
    target.write_text(
        json.dumps(index.to_dict(), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return target


def load_bm25_index(paper_id: str, path: Path | None = None) -> PaperBM25Index:
    source = path or default_bm25_index_path(paper_id)
    payload = json.loads(source.read_text(encoding="utf-8"))
    index = PaperBM25Index.from_dict(payload)
    if index.paper_id != paper_id:
        raise ValueError(f"BM25 index paper_id mismatch: {index.paper_id!r} != {paper_id!r}")
    return index


def _chunk_index_text(chunk: PaperChunk) -> str:
    metadata = chunk.metadata
    parts = [
        chunk.section_title,
        chunk.content,
        chunk.formula_latex,
        chunk.formula_description,
        str(metadata.get("caption") or ""),
        str(metadata.get("visual_description") or ""),
        str(metadata.get("table_text") or ""),
        " ".join(str(item) for item in metadata.get("table_columns") or []),
    ]
    return "\n".join(part for part in parts if part)


def _tokenize(text: str) -> list[str]:
    return [match.group(0).casefold() for match in _TOKEN_RE.finditer(text or "")]


def _postings_from_tokenized_docs(tokenized_docs: list[list[str]]) -> dict[str, dict[int, int]]:
    postings: dict[str, dict[int, int]] = {}
    for doc_index, tokens in enumerate(tokenized_docs):
        for token in tokens:
            doc_postings = postings.setdefault(token, {})
            doc_postings[doc_index] = doc_postings.get(doc_index, 0) + 1
    return postings


def _coerce_postings(payload: Any) -> dict[str, dict[int, int]]:
    if not isinstance(payload, dict):
        return {}
    postings: dict[str, dict[int, int]] = {}
    for token, raw_doc_freqs in payload.items():
        if not isinstance(raw_doc_freqs, dict):
            continue
        coerced: dict[int, int] = {}
        for doc_index, freq in raw_doc_freqs.items():
            coerced[int(doc_index)] = int(freq)
        postings[str(token)] = coerced
    return postings


__all__ = [
    "BM25Hit",
    "PaperBM25Index",
    "default_bm25_index_path",
    "load_bm25_index",
    "write_bm25_index",
]
