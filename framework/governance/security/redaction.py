from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from framework.shared.redaction import Redactor


class SecurityRedactor:
    def __init__(self, redactor: Redactor | None = None) -> None:
        self.redactor = redactor or Redactor()

    def redact(self, value: Any) -> Any:
        return self.redactor.redact(value)

    def redact_text(self, text: str) -> str:
        return str(self.redactor.redact(str(text)))

    def redact_mapping(self, mapping: Mapping[str, Any]) -> dict[str, Any]:
        return self.redactor.redact_mapping(mapping)
