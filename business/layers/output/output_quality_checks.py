from __future__ import annotations

from business.foundation import BoardCard, BusinessQualityCheck, Report


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
        BusinessQualityCheck.create(
            "card_has_provenance",
            passed=card.provenance is not None,
            severity="warning",
            reason="BoardCard should include provenance.",
        ),
        BusinessQualityCheck.create(
            "card_has_quality_snapshot",
            passed=card.quality is not None,
            severity="warning",
            reason="BoardCard should include quality snapshot.",
        ),
    ]


def check_report_output_quality(report: Report) -> list[BusinessQualityCheck]:
    return [
        BusinessQualityCheck.create(
            "report_has_cards",
            passed=bool(report.cards),
            severity="warning",
            reason="Report should include cards.",
        ),
        BusinessQualityCheck.create(
            "report_has_sections",
            passed=bool(report.sections),
            severity="warning",
            reason="Report should include sections.",
        ),
    ]


__all__ = ["check_card_output_quality", "check_report_output_quality"]
