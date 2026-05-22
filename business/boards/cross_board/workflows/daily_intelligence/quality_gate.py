from __future__ import annotations

from typing import Any

from business.memory.historian_quality_checks import HistorianQualityChecker


class DailyIntelligenceQualityGate:
    def __init__(
        self,
        historian_quality_checker: HistorianQualityChecker | None = None,
    ) -> None:
        self.historian_quality_checker = historian_quality_checker or HistorianQualityChecker()

    def evaluate(self, report_draft: dict[str, Any]) -> dict[str, Any]:
        historian_quality = self.historian_quality_checker.check_report(report_draft)
        critical_issues = historian_quality.critical_issues()
        high_issues = historian_quality.high_issues()
        if critical_issues:
            passed = False
            decision = "blocked"
            reason = "blocked_by_historian_quality"
        else:
            passed = True
            decision = "passed"
            reason = "ok"
        return {
            "passed": passed,
            "decision": decision,
            "reason": reason,
            "historian_quality": historian_quality.to_dict(),
            "issue_count": len(historian_quality.issues),
            "high_or_critical_issue_count": len(high_issues) + len(critical_issues),
        }


__all__ = ["DailyIntelligenceQualityGate"]
