from __future__ import annotations

from framework.shared import (
    REDACTED_VALUE,
    RedactionRule,
    Redactor,
    contains_redacted_value,
    redact_sensitive_values,
)


def test_redact_sensitive_values_handles_nested_structures() -> None:
    payload = redact_sensitive_values(
        {
            "api_key": "secret",
            "nested": [{"password": "hidden"}, {"safe": "visible"}],
            "message": "Bearer abcdef1234567890",
        }
    )

    assert payload == {
        "api_key": REDACTED_VALUE,
        "nested": [{"password": REDACTED_VALUE}, {"safe": "visible"}],
        "message": REDACTED_VALUE,
    }
    assert contains_redacted_value(payload) is True


def test_redactor_supports_custom_rules_and_dsn_strings() -> None:
    redactor = Redactor([RedactionRule(key_tokens=("auth",), replacement="[hidden]")])
    dsn = "postgresql://user:pass@localhost/news"

    assert redactor.redact({"authorization": "secret"}) == {"authorization": "[hidden]"}
    assert redactor.redact({"message": f"connect {dsn}"}) == {
        "message": "connect postgresql://[hidden]@localhost/news"
    }


def test_redaction_rule_matches_case_insensitive_key_tokens() -> None:
    rule = RedactionRule(key_tokens=("api_key",))

    assert rule.matches_key("X-API-Key")
    assert not rule.matches_key("topic")
