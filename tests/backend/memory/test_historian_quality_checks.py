from backend.memory.historian_quality_checks import HistorianQualityChecker


def test_historian_quality_passes_when_no_historian_metadata() -> None:
    result = HistorianQualityChecker().check_report({"metadata": {}})

    assert result.passed is True
    assert result.issues == []
    assert result.metadata["historian_available"] is False


def test_historian_quality_flags_contradictions() -> None:
    result = HistorianQualityChecker().check_report(
        {
            "metadata": {
                "historian": {
                    "output": {
                        "contradictions": ["Historical contradiction"],
                    }
                }
            }
        }
    )

    assert result.passed is True
    assert result.high_issues()
    assert result.high_issues()[0].issue_type == "historian_contradictions"
    assert result.high_issues()[0].severity == "high"


def test_historian_quality_flags_repeated_claims() -> None:
    result = HistorianQualityChecker().check_report(
        {
            "metadata": {
                "historian": {
                    "output": {
                        "is_new_event": False,
                        "repeated_claims": ["Repeated historical claim"],
                    }
                }
            }
        }
    )

    issue = result.issues[0]
    assert issue.issue_type == "historian_repeated_claims"
    assert issue.severity == "medium"


def test_historian_quality_records_recommendations() -> None:
    result = HistorianQualityChecker().check_report(
        {
            "metadata": {
                "historian": {
                    "output": {
                        "recommendations": ["Run quality gate before publishing."],
                    }
                }
            }
        }
    )

    issue = result.issues[0]
    assert issue.issue_type == "historian_recommendations"
    assert issue.severity == "low"
