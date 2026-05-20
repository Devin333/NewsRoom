from datetime import UTC, datetime

from infrastructure.storage.security import REDACTED_VALUE, RedactionReport, StorageRedactor


def test_redaction_report_round_trips() -> None:
    report = RedactionReport(
        run_id="run-1",
        artifact_id="events",
        redacted_fields=["$.payload.api_key"],
        redaction_rules_applied=["sensitive_key"],
        created_at=datetime(2026, 5, 11, 1, 0, tzinfo=UTC),
    )

    restored = RedactionReport.from_dict(report.to_dict())

    assert restored == report
    assert restored.to_dict()["created_at"] == "2026-05-11T01:00:00Z"


def test_storage_redactor_redacts_nested_sensitive_values_and_reports_rules() -> None:
    fake_secret = "sk" + "-abcdef1234567890"
    payload = {
        "api_key": fake_secret,
        "headers": {"authorization": "Bearer runtime-token"},
        "nested": {
            "message": f"failed with {fake_secret}",
            "url": "https://example.com/feed?token=value&topic=ai",
        },
        "safe": "visible",
    }

    result = StorageRedactor().redact(payload, run_id="run-1", artifact_id="events")

    assert result.redacted is True
    assert result.value["api_key"] == REDACTED_VALUE
    assert result.value["headers"]["authorization"] == REDACTED_VALUE
    assert fake_secret not in str(result.value)
    assert REDACTED_VALUE in result.value["nested"]["message"]
    assert "token=%5Bredacted%5D" in result.value["nested"]["url"]
    assert result.value["safe"] == "visible"
    assert result.report.redacted_fields == [
        "$.api_key",
        "$.headers.authorization",
        "$.nested.message",
        "$.nested.url",
    ]
    assert result.report.redaction_rules_applied == [
        "secret_like_string",
        "sensitive_key",
        "sensitive_url_query",
    ]


def test_storage_redactor_returns_empty_report_when_no_redaction_needed() -> None:
    result = StorageRedactor().redact({"safe": ["visible"]}, run_id="run-1", artifact_id="events")

    assert result.redacted is False
    assert result.value == {"safe": ["visible"]}
    assert result.report.redacted_fields == []
    assert result.report.redaction_rules_applied == []
