from __future__ import annotations

from framework.shared.errors import ValidationError


class HarnessValidationError(ValidationError):
    """Raised when a Harness contract is invalid."""


__all__ = ["HarnessValidationError"]
