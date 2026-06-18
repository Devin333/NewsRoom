from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from framework.shared.redaction import RedactionRule, Redactor


REDACTED_VALUE = "[redacted]"
_TOOL_REDACTOR = Redactor([RedactionRule(replacement=REDACTED_VALUE)])


class ToolRedactor:
    def redact(self, value: Any) -> Any:
        return _TOOL_REDACTOR.redact(value)

    def redact_result(self, result: Any) -> Any:
        if hasattr(result, "to_dict"):
            return self.redact(result.to_dict())
        return self.redact(result)


def redact_sensitive_values(value: Any) -> Any:
    return _TOOL_REDACTOR.redact(value)


def contains_redacted_value(value: Any) -> bool:
    if value == REDACTED_VALUE:
        return True
    if isinstance(value, Mapping):
        return any(contains_redacted_value(item) for item in value.values())
    if isinstance(value, (list, tuple, set)):
        return any(contains_redacted_value(item) for item in value)
    return False


_REDACTED_BOOL_PREFIXES = (
    "has_",
    "is_",
    "used_",
    "can_",
    "should_",
    "supports_",
)


def restore_redacted_booleans(value: Any, original: Any) -> Any:
    if value == REDACTED_VALUE and isinstance(original, bool):
        return original
    if isinstance(value, Mapping) and isinstance(original, Mapping):
        restored: dict[Any, Any] = {}
        for key, item in value.items():
            original_item = original.get(key)
            if (
                item == REDACTED_VALUE
                and isinstance(original_item, bool)
                and _is_boolean_result_key(str(key))
            ):
                restored[key] = original_item
            else:
                restored[key] = restore_redacted_booleans(item, original_item)
        return restored
    if isinstance(value, list) and isinstance(original, list):
        return [
            restore_redacted_booleans(item, original[index] if index < len(original) else None)
            for index, item in enumerate(value)
        ]
    if isinstance(value, tuple) and isinstance(original, tuple):
        return tuple(
            restore_redacted_booleans(item, original[index] if index < len(original) else None)
            for index, item in enumerate(value)
        )
    return value


def reject_sensitive_mapping_keys(value: Mapping[str, Any], *, label: str = "payload") -> None:
    for key, item in value.items():
        normalized = str(key).casefold().replace("-", "_")
        if any(token in normalized for token in _sensitive_key_tokens()):
            raise ValueError(f"{label} key is not allowed: {key}")
        if isinstance(item, Mapping):
            reject_sensitive_mapping_keys(item, label=label)


def _sensitive_key_tokens() -> tuple[str, ...]:
    from framework.shared.redaction import DEFAULT_SENSITIVE_KEY_TOKENS

    return DEFAULT_SENSITIVE_KEY_TOKENS


def _is_boolean_result_key(key: str) -> bool:
    normalized = re.sub(r"[^a-z0-9_]+", "_", key.casefold())
    return normalized.endswith("_credential") or normalized.startswith(_REDACTED_BOOL_PREFIXES)
