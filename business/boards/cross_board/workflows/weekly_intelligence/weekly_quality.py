from __future__ import annotations

from typing import Any


class WeeklyQualityBuilder:
    def build(self, source_reports: list[dict[str, Any]], weekly_trends: dict[str, Any]) -> dict[str, Any]:
        source_url_count = sum(len(report.get("source_urls") or []) for report in source_reports)
        evidence_coverage = 1.0 if source_url_count else 0.0
        trend_count = len(weekly_trends.get("high_confidence_trends") or [])
        weak_count = len(weekly_trends.get("weak_signal_trends") or [])
        score = round(min(1.0, 0.35 + evidence_coverage * 0.25 + min(0.3, trend_count * 0.08) + min(0.1, len(source_reports) * 0.03)), 4)
        weak_spots = []
        if not source_reports:
            weak_spots.append("no_source_reports")
        if not source_url_count:
            weak_spots.append("missing_source_urls")
        if weak_count > trend_count:
            weak_spots.append("weak_signals_outnumber_high_confidence_trends")
        return {
            "score": score,
            "source_coverage": {"source_report_count": len(source_reports), "source_url_count": source_url_count},
            "evidence_coverage": evidence_coverage,
            "board_coverage": _board_coverage(source_reports),
            "trend_confidence": {
                "high_confidence_trend_count": trend_count,
                "weak_signal_trend_count": weak_count,
            },
            "weak_spots": weak_spots,
        }


def _board_coverage(source_reports: list[dict[str, Any]]) -> dict[str, int]:
    coverage: dict[str, int] = {}
    for report in source_reports:
        metadata = report.get("metadata") if isinstance(report.get("metadata"), dict) else {}
        for board_type in metadata.get("board_outputs", {}) if isinstance(metadata.get("board_outputs"), dict) else []:
            coverage[str(board_type)] = coverage.get(str(board_type), 0) + 1
    return coverage or {"cross_board": len(source_reports)}


__all__ = ["WeeklyQualityBuilder"]
