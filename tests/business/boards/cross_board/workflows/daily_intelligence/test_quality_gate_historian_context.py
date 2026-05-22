from business.boards.cross_board.workflows.daily_intelligence.quality_gate import DailyIntelligenceQualityGate
from business.memory.historian_quality_checks import HistorianQualityIssue, HistorianQualityResult


def test_quality_gate_includes_historian_quality() -> None:
    report_draft = {
        "metadata": {
            "historian": {
                "output": {
                    "contradictions": ["Historical contradiction"],
                }
            }
        }
    }

    result = DailyIntelligenceQualityGate().evaluate(report_draft)

    assert result["passed"] is True
    assert result["decision"] == "passed"
    assert result["historian_quality"]["issues"][0]["issue_type"] == "historian_contradictions"
    assert result["high_or_critical_issue_count"] == 1


def test_quality_gate_blocks_critical_historian_issue() -> None:
    result = DailyIntelligenceQualityGate(
        historian_quality_checker=_CriticalHistorianQualityChecker()
    ).evaluate({"metadata": {}})

    assert result["passed"] is False
    assert result["decision"] == "blocked"
    assert result["reason"] == "blocked_by_historian_quality"


class _CriticalHistorianQualityChecker:
    def check_report(self, report_draft):
        return HistorianQualityResult(
            passed=False,
            issues=[
                HistorianQualityIssue(
                    issue_type="historian_critical",
                    severity="critical",
                    message="Critical historian issue.",
                )
            ],
        )
