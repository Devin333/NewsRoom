from __future__ import annotations

import re


_TOKEN_RE = re.compile(r"[A-Za-z0-9_]+|[\u4e00-\u9fff]")
_STOP_WORDS = {
    "about",
    "around",
    "chunk",
    "does",
    "evidence",
    "explain",
    "explained",
    "field",
    "paper",
    "relation",
    "show",
    "shows",
    "surrounding",
    "text",
    "what",
    "which",
    "with",
}


class LightweightLexicalReranker:
    """Deterministic lexical reranker for benchmark/live smoke runs."""

    def score(self, query: str, passages: list[str]) -> list[float]:
        query_tokens = _content_tokens(query)
        if not query_tokens:
            return [0.0 for _passage in passages]
        query_set = set(query_tokens)
        query_phrase = " ".join(query_tokens)
        scores: list[float] = []
        for passage in passages:
            passage_tokens = _content_tokens(passage)
            if not passage_tokens:
                scores.append(0.0)
                continue
            passage_set = set(passage_tokens)
            overlap = len(query_set & passage_set) / len(query_set)
            passage_phrase = " ".join(passage_tokens)
            if query_phrase and query_phrase in passage_phrase:
                overlap = max(overlap, 0.95)
            if _has_ordered_anchor_match(query_tokens, passage_tokens):
                overlap = max(overlap, min(1.0, overlap + 0.12))
            scores.append(round(max(0.0, min(1.0, overlap)), 6))
        return scores


def _content_tokens(text: str) -> list[str]:
    return [
        token.casefold()
        for token in _TOKEN_RE.findall(str(text or ""))
        if len(token.strip()) > 1 and token.casefold() not in _STOP_WORDS
    ]


def _has_ordered_anchor_match(query_tokens: list[str], passage_tokens: list[str]) -> bool:
    anchors = [token for token in query_tokens if len(token) >= 4]
    if len(anchors) < 2:
        return False
    positions = []
    for anchor in anchors[:4]:
        try:
            positions.append(passage_tokens.index(anchor))
        except ValueError:
            return False
    return positions == sorted(positions)


__all__ = ["LightweightLexicalReranker"]
