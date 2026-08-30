from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class HistorianQualityIssue:
    issue_type: str
    severity: str
    message: str
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "issue_type": self.issue_type,
            "severity": self.severity,
            "message": self.message,
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class HistorianQualityResult:
    passed: bool
    issues: list[HistorianQualityIssue] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def critical_issues(self) -> list[HistorianQualityIssue]:
        return [issue for issue in self.issues if issue.severity == "critical"]

    def high_issues(self) -> list[HistorianQualityIssue]:
        return [issue for issue in self.issues if issue.severity == "high"]

    def to_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "issues": [issue.to_dict() for issue in self.issues],
            "metadata": dict(self.metadata),
        }


class HistorianQualityChecker:
    def check_report(self, report_draft: dict[str, Any]) -> HistorianQualityResult:
        metadata = report_draft.get("metadata") if isinstance(report_draft, dict) else None
        historian = metadata.get("historian") if isinstance(metadata, dict) else None
        if not isinstance(historian, dict):
            return HistorianQualityResult(
                passed=True,
                issues=[],
                metadata={"historian_available": False},
            )

        output = historian.get("output")
        if not isinstance(output, dict):
            return HistorianQualityResult(
                passed=True,
                issues=[],
                metadata={"historian_available": True, "missing_output": True},
            )

        contradictions = [str(item) for item in output.get("contradictions") or [] if item is not None]
        repeated_claims = [str(item) for item in output.get("repeated_claims") or [] if item is not None]
        recommendations = [str(item) for item in output.get("recommendations") or [] if item is not None]
        is_new_event = bool(output.get("is_new_event", False))
        issues: list[HistorianQualityIssue] = []

        if contradictions:
            issues.append(
                HistorianQualityIssue(
                    issue_type="historian_contradictions",
                    severity="high",
                    message="Historian found contradictions in the historical context.",
                    metadata={"contradictions": contradictions},
                )
            )
        if repeated_claims and not is_new_event:
            issues.append(
                HistorianQualityIssue(
                    issue_type="historian_repeated_claims",
                    severity="medium",
                    message="Historian suggests this is a repeated or follow-up claim rather than a new event.",
                    metadata={"repeated_claims": repeated_claims},
                )
            )
        if recommendations:
            issues.append(
                HistorianQualityIssue(
                    issue_type="historian_recommendations",
                    severity="low",
                    message="Historian provided recommendations for this report.",
                    metadata={"recommendations": recommendations},
                )
            )

        result = HistorianQualityResult(
            passed=not any(issue.severity == "critical" for issue in issues),
            issues=issues,
            metadata={
                "historian_available": True,
                "contradiction_count": len(contradictions),
                "repeated_claim_count": len(repeated_claims),
                "recommendation_count": len(recommendations),
                "is_new_event": is_new_event,
            },
        )
        return result


__all__ = ["HistorianQualityChecker", "HistorianQualityIssue", "HistorianQualityResult"]
