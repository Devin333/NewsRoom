from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from framework.shared.result import ErrorDetail


class FrameworkError(Exception):
    def __init__(
        self,
        message: str,
        *,
        code: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.code = code or self.__class__.__name__
        self.details = dict(details or {})

    def to_error_detail(self) -> "ErrorDetail":
        from framework.shared.result import ErrorDetail

        return ErrorDetail(
            code=self.code,
            message=self.message,
            details=dict(self.details),
        )


class ValidationError(FrameworkError):
    pass


class ConfigurationError(FrameworkError):
    pass


class DependencyError(FrameworkError):
    pass


class RuntimeExecutionError(FrameworkError):
    pass


class BoundaryViolationError(FrameworkError):
    pass
