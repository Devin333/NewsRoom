from __future__ import annotations

from business.foundation import BoardCard, BusinessQualityCheck


def check_card_output_quality(card: BoardCard) -> list[BusinessQualityCheck]:
    return [
        BusinessQualityCheck.create(
            "card_has_ranking_reason",
            passed=bool(card.ranking_reason),
            severity="warning",
            reason="BoardCard should include ranking_reason.",
        ),
        BusinessQualityCheck.create(
            "card_has_evidence_refs",
            passed=bool(card.evidence_refs),
            severity="warning",
            reason="BoardCard should include evidence_refs.",
        ),
    ]
