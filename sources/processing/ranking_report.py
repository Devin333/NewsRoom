from __future__ import annotations

from domain.sources import RankedSourceItem, SourceRankingScore


def build_source_ranking_scores(ranked_items: list[RankedSourceItem]) -> list[SourceRankingScore]:
    scores: list[SourceRankingScore] = []
    for ranked in ranked_items:
        lineage = ranked.metadata.get("lineage") if isinstance(ranked.metadata.get("lineage"), dict) else {}
        authority_score = float(lineage.get("authority_score", 0.0))
        scores.append(
            SourceRankingScore(
                ranked_item_id=ranked.ranked_item_id,
                normalized_item_id=ranked.item.normalized_item_id,
                source_item_id=ranked.item.source_item_id,
                source_id=ranked.item.source_id,
                title=ranked.item.title,
                url=ranked.item.canonical_url,
                relevance_score=ranked.relevance_score,
                recency_score=ranked.recency_score,
                reliability_score=ranked.reliability_score,
                authority_score=round(authority_score, 4),
                novelty_score=ranked.novelty_score,
                final_score=ranked.final_score,
                rank_reason=ranked.rank_reason,
            )
        )
    return scores
