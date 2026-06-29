from __future__ import annotations

import hashlib
import re
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Protocol

from business.research.document.models import PaperChunk


_TOKEN_RE = re.compile(r"[A-Za-z0-9_]+")
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+|\n+")
_STOPWORDS = {
    "about",
    "after",
    "also",
    "and",
    "are",
    "can",
    "for",
    "from",
    "has",
    "have",
    "how",
    "into",
    "its",
    "may",
    "more",
    "our",
    "paper",
    "passage",
    "that",
    "the",
    "their",
    "this",
    "through",
    "what",
    "when",
    "which",
    "with",
}
_CLAIM_SIGNAL_TERMS = {
    "achieve",
    "achieves",
    "accuracy",
    "approach",
    "conclude",
    "contribution",
    "define",
    "defines",
    "demonstrate",
    "demonstrates",
    "find",
    "finds",
    "improve",
    "improves",
    "introduce",
    "introduces",
    "method",
    "model",
    "outperform",
    "outperforms",
    "propose",
    "proposes",
    "provide",
    "provides",
    "result",
    "results",
    "show",
    "shows",
    "suggest",
    "suggests",
}
_CLAIM_SECTION_TITLES = ("abstract", "introduction", "conclusion", "discussion", "result", "results")


@dataclass(frozen=True)
class ClaimRecord:
    claim_id: str
    paper_id: str
    chunk_id: str
    section_title: str
    claim_text: str
    source_locator: str
    claim_type: str

    def to_dict(self) -> dict[str, str]:
        return {
            "claim_id": self.claim_id,
            "paper_id": self.paper_id,
            "chunk_id": self.chunk_id,
            "section_title": self.section_title,
            "claim_text": self.claim_text,
            "source_locator": self.source_locator,
            "claim_type": self.claim_type,
        }


@dataclass(frozen=True)
class ClaimSearchHit:
    record: ClaimRecord
    score: float


class PaperClaimSearchPort(Protocol):
    def search_claims(self, paper_id: str, query_text: str, *, limit: int = 10) -> list[ClaimSearchHit]: ...


class PaperClaimIndex:
    def __init__(self, records: Iterable[ClaimRecord] = ()) -> None:
        self._records = tuple(records)

    @classmethod
    def from_chunks(cls, chunks: Iterable[PaperChunk]) -> "PaperClaimIndex":
        records: list[ClaimRecord] = []
        for chunk in chunks:
            records.extend(extract_claim_records(chunk))
        return cls(records)

    @property
    def records(self) -> tuple[ClaimRecord, ...]:
        return self._records

    def search_claims(self, paper_id: str, query_text: str, *, limit: int = 10) -> list[ClaimSearchHit]:
        scored: list[ClaimSearchHit] = []
        query_terms = _content_terms(query_text)
        if not query_terms:
            return []
        for record in self._records:
            if record.paper_id != paper_id:
                continue
            score = _claim_score(query_terms, record)
            if score <= 0.0:
                continue
            scored.append(ClaimSearchHit(record=record, score=round(score, 6)))
        scored.sort(key=lambda hit: (hit.score, hit.record.claim_id), reverse=True)
        return scored[: max(0, int(limit))]


def extract_claim_records(chunk: PaperChunk) -> list[ClaimRecord]:
    if chunk.chunk_type not in {"abstract", "paragraph"}:
        return []
    records: list[ClaimRecord] = []
    for sentence in _claim_sentences(chunk.content):
        if not _is_claim_like(sentence, chunk):
            continue
        records.append(ClaimRecord(
            claim_id=_claim_id(chunk, sentence),
            paper_id=chunk.paper_id,
            chunk_id=chunk.chunk_id,
            section_title=chunk.section_title,
            claim_text=sentence,
            source_locator=_source_locator(chunk),
            claim_type=_claim_type(chunk),
        ))
    return records


def _claim_sentences(text: str) -> list[str]:
    out: list[str] = []
    for raw in _SENTENCE_SPLIT_RE.split(str(text or "")):
        sentence = " ".join(raw.split())
        sentence = re.sub(r"^sec:[A-Za-z0-9_.:-]+\s+", "", sentence)
        if sentence:
            out.append(sentence)
    return out


def _is_claim_like(sentence: str, chunk: PaperChunk) -> bool:
    terms = _content_terms(sentence)
    if len(terms) < 6 or len(terms) > 80:
        return False
    if _looks_like_reference_or_formula(sentence):
        return False
    title = chunk.section_title.casefold()
    section_is_claim_dense = chunk.chunk_type == "abstract" or any(token in title for token in _CLAIM_SECTION_TITLES)
    has_signal = bool(set(terms) & _CLAIM_SIGNAL_TERMS)
    return section_is_claim_dense or has_signal


def _looks_like_reference_or_formula(sentence: str) -> bool:
    text = sentence.strip()
    if text.count("[") + text.count("]") >= 4:
        return True
    if len(re.findall(r"\\[A-Za-z]+|[=<>]", text)) >= 4:
        return True
    return False


def _claim_score(query_terms: list[str], record: ClaimRecord) -> float:
    query_set = set(query_terms)
    if not query_set:
        return 0.0
    claim_terms = set(_content_terms(f"{record.section_title} {record.claim_text}"))
    if not claim_terms:
        return 0.0
    overlap = query_set & claim_terms
    if not overlap:
        return 0.0
    query_recall = len(overlap) / len(query_set)
    claim_precision = len(overlap) / len(claim_terms)
    signal_bonus = 0.08 if set(_content_terms(record.claim_text)) & _CLAIM_SIGNAL_TERMS else 0.0
    return min(1.0, (query_recall * 0.75) + (claim_precision * 0.20) + signal_bonus)


def _content_terms(text: str) -> list[str]:
    terms = [
        token.casefold()
        for token in _TOKEN_RE.findall(str(text or ""))
        if len(token) > 2
    ]
    return [term for term in terms if term not in _STOPWORDS]


def _claim_type(chunk: PaperChunk) -> str:
    roles = {str(role).casefold() for role in chunk.section_role}
    title = chunk.section_title.casefold()
    if chunk.chunk_type == "abstract" or "abstract" in title:
        return "abstract_claim"
    if "conclusion" in roles or "conclusion" in title:
        return "conclusion_claim"
    if roles & {"experiment", "analysis"} or any(token in title for token in ("result", "results", "analysis")):
        return "result_claim"
    if "method" in roles or "method" in title:
        return "method_claim"
    return "paragraph_claim"


def _source_locator(chunk: PaperChunk) -> str:
    return str(chunk.metadata.get("source_locator") or chunk.metadata.get("source_ref") or "")


def _claim_id(chunk: PaperChunk, sentence: str) -> str:
    payload = f"{chunk.paper_id}:{chunk.chunk_id}:{sentence}"
    return "claim_" + hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


__all__ = [
    "ClaimRecord",
    "ClaimSearchHit",
    "PaperClaimIndex",
    "PaperClaimSearchPort",
    "extract_claim_records",
]
