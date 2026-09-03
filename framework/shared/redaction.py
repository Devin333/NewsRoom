from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

REDACTED_VALUE = "***REDACTED***"
DEFAULT_SENSITIVE_KEY_TOKENS = (
    "api_key",
    "apikey",
    "authorization",
    "client_secret",
    "cookie",
    "credential",
    "dsn",
    "password",
    "private_key",
    "secret",
    "token",
)

_SECRET_PREFIX = "sk" + "-"
_SECRET_PATTERNS = (
    re.compile(rf"(?<![A-Za-z0-9_-]){_SECRET_PREFIX}[A-Za-z0-9_-]{{8,}}(?![A-Za-z0-9_-])"),
    re.compile(r"Bearer\s+[A-Za-z0-9._~+/=-]{8,}", re.IGNORECASE),
    re.compile(r"([a-z][a-z0-9+.-]*://)([^/\s:@?#]+):([^@\s/?#]+)@", re.IGNORECASE),
)


@dataclass(frozen=True)
class RedactionRule:
    key_tokens: tuple[str, ...] = DEFAULT_SENSITIVE_KEY_TOKENS
    replacement: str = REDACTED_VALUE

    def matches_key(self, key: str) -> bool:
        normalized = str(key).casefold().replace("-", "_")
        return any(token.casefold() in normalized for token in self.key_tokens)


class Redactor:
    def __init__(self, rules: list[RedactionRule] | None = None) -> None:
        self.rules = list(rules or [RedactionRule()])

    def redact(self, value: Any) -> Any:
        if isinstance(value, Mapping):
            return self.redact_mapping(value)
        if isinstance(value, list):
            return [self.redact(item) for item in value]
        if isinstance(value, tuple):
            return tuple(self.redact(item) for item in value)
        if isinstance(value, set):
            return {self.redact(item) for item in value}
        if isinstance(value, str):
            return self._redact_secret_like_string(value)
        return value

    def redact_mapping(self, value: Mapping[str, Any]) -> dict[str, Any]:
        return {
            key: self._replacement_for_key(str(key)) if self._matches_key(str(key)) else self.redact(item)
            for key, item in value.items()
        }

    def contains_sensitive_key(self, value: Mapping[str, Any]) -> bool:
        return any(self._matches_key(str(key)) for key in value)

    def _matches_key(self, key: str) -> bool:
        return any(rule.matches_key(key) for rule in self.rules)

    def _replacement_for_key(self, key: str) -> str:
        for rule in self.rules:
            if rule.matches_key(key):
                return rule.replacement
        return REDACTED_VALUE

    def _redact_secret_like_string(self, value: str) -> str:
        redacted = value
        replacement = self.rules[0].replacement if self.rules else REDACTED_VALUE
        redacted = _SECRET_PATTERNS[0].sub(replacement, redacted)
        redacted = _SECRET_PATTERNS[1].sub(replacement, redacted)
        redacted = _SECRET_PATTERNS[2].sub(lambda match: f"{match.group(1)}{replacement}@", redacted)
        return redacted


def redact_sensitive_values(value: Any) -> Any:
    return Redactor().redact(value)


def contains_redacted_value(value: Any) -> bool:
    if value == REDACTED_VALUE:
        return True
    if isinstance(value, Mapping):
        return any(contains_redacted_value(item) for item in value.values())
    if isinstance(value, (list, tuple, set)):
        return any(contains_redacted_value(item) for item in value)
    return False
