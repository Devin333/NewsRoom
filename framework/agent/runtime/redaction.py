from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from framework.shared.redaction import RedactionRule, Redactor


REDACTED_VALUE = "[redacted]"
_AGENT_REDACTOR = Redactor([RedactionRule(replacement=REDACTED_VALUE)])


def redact_sensitive_values(value: Any) -> Any:
    return _AGENT_REDACTOR.redact(value)


def contains_redacted_value(value: Any) -> bool:
    if value == REDACTED_VALUE:
        return True
    if isinstance(value, Mapping):
        return any(contains_redacted_value(item) for item in value.values())
    if isinstance(value, (list, tuple, set)):
        return any(contains_redacted_value(item) for item in value)
    return False
