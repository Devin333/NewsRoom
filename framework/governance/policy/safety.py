from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from framework.shared.errors import ValidationError
from framework.shared.json import stable_json_dumps
from framework.shared.redaction import DEFAULT_SENSITIVE_KEY_TOKENS


@dataclass(frozen=True)
class SafetyPolicy:
    blocked_payload_key_tokens: tuple[str, ...] = DEFAULT_SENSITIVE_KEY_TOKENS
    blocked_tool_names: tuple[str, ...] = field(default_factory=tuple)
    blocked_tool_namespaces: tuple[str, ...] = field(default_factory=tuple)
    max_payload_bytes: int | None = None

    def __post_init__(self) -> None:
        if self.max_payload_bytes is not None and self.max_payload_bytes < 0:
            raise ValidationError("max_payload_bytes must be non-negative", code="invalid_safety_policy")

    def check_payload(self, payload: Any) -> list[str]:
        violations: list[str] = []
        self._check_payload_keys(payload, path="", violations=violations)
        if self.max_payload_bytes is not None:
            actual_bytes = len(stable_json_dumps(payload).encode("utf-8"))
            if actual_bytes > self.max_payload_bytes:
                violations.append(
                    f"payload size {actual_bytes} bytes exceeds limit {self.max_payload_bytes} bytes"
                )
        return violations

    def check_tool_call(self, call: Any) -> list[str]:
        name = _read_field(call, "name") or _read_field(call, "tool_name")
        if name is None:
            return []
        tool_name = str(name)
        violations: list[str] = []
        if tool_name in self.blocked_tool_names:
            violations.append(f"tool {tool_name} is blocked")
        namespace = str(_read_field(call, "namespace") or tool_name.split(".", 1)[0])
        if namespace in self.blocked_tool_namespaces:
            violations.append(f"tool namespace {namespace} is blocked")
        return violations

    def _check_payload_keys(self, value: Any, *, path: str, violations: list[str]) -> None:
        if isinstance(value, Mapping):
            for key, item in value.items():
                key_text = str(key)
                current_path = f"{path}.{key_text}" if path else key_text
                normalized = key_text.casefold().replace("-", "_")
                for token in self.blocked_payload_key_tokens:
                    if token.casefold() in normalized:
                        violations.append(f"sensitive payload key {current_path} is not allowed")
                        break
                self._check_payload_keys(item, path=current_path, violations=violations)
        elif isinstance(value, (list, tuple, set, frozenset)):
            for index, item in enumerate(value):
                self._check_payload_keys(item, path=f"{path}[{index}]", violations=violations)


def _read_field(value: Any, name: str) -> Any:
    if isinstance(value, Mapping):
        return value.get(name)
    return getattr(value, name, None)
