from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Mapping


@dataclass(frozen=True)
class FieldScoreResult:
    query_terms: tuple[str, ...]
    field_scores: dict[str, float]
    best_field: str = ""
    best_score: float = 0.0


def score_fields(
    query: str,
    fields: Mapping[str, str],
    *,
    field_weights: Mapping[str, float] | None = None,
) -> FieldScoreResult:
    query_terms = _token_set(query)
    if not query_terms:
        return FieldScoreResult(query_terms=(), field_scores={})
    weights = {str(key): float(value) for key, value in dict(field_weights or {}).items()}
    scores: dict[str, float] = {}
    for field_name, text in fields.items():
        field_terms = _token_set(text)
        if not field_terms:
            continue
        overlap = len(query_terms & field_terms)
        raw_score = overlap / len(query_terms)
        weight = weights.get(str(field_name), 1.0)
        scores[str(field_name)] = raw_score * weight
    if not scores:
        return FieldScoreResult(query_terms=tuple(sorted(query_terms)), field_scores={})
    best_field, best_score = max(scores.items(), key=lambda item: (item[1], item[0]))
    return FieldScoreResult(
        query_terms=tuple(sorted(query_terms)),
        field_scores=scores,
        best_field=best_field,
        best_score=best_score,
    )


def _token_set(text: str) -> set[str]:
    return {match.group(0).casefold() for match in re.finditer(r"[A-Za-z0-9_]+", str(text or ""))}


__all__ = ["FieldScoreResult", "score_fields"]
