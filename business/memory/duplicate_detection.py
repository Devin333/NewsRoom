from __future__ import annotations

from business.foundation import BoardCard
from business.memory.models import BusinessMemoryHit


def estimate_historical_duplicate_score(card: BoardCard, hits: list[BusinessMemoryHit]) -> float:
    if not hits:
        return 0.0
    card_title = _tokens(card.title)
    card_sources = {ref.source_id or ref.source_name for ref in card.evidence_refs}
    card_evidence_ids = {ref.source_id for ref in card.evidence_refs if ref.source_id}
    best = 0.0
    for hit in hits:
        title_overlap = _jaccard(card_title, _tokens(hit.text or hit.metadata.get("title") or ""))
        source_match = bool(hit.source_item_id and hit.source_item_id in card_sources)
        evidence_match = bool(hit.evidence_id and hit.evidence_id in card_evidence_ids)
        topic_match = bool(hit.topic and str(hit.topic).casefold() in _card_text(card))
        score = 0.0
        if title_overlap >= 0.75:
            score += 0.55
        elif title_overlap >= 0.45:
            score += 0.3
        if source_match:
            score += 0.25
        if evidence_match:
            score += 0.45
        if topic_match:
            score += 0.15
        best = max(best, score)
    return _clamp(best)


def _tokens(text: object) -> set[str]:
    return {token for token in "".join(ch.casefold() if ch.isalnum() else " " for ch in str(text)).split() if len(token) > 2}


def _jaccard(left: set[str], right: set[str]) -> float:
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)


def _card_text(card: BoardCard) -> str:
    return f"{card.title} {card.summary} {' '.join(card.ranking_features)}".casefold()


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, float(value)))
