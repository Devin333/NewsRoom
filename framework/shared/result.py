from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Generic, TypeVar

from framework.shared.json import to_jsonable

T = TypeVar("T")


@dataclass(frozen=True)
class ErrorDetail:
    code: str
    message: str
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "details": to_jsonable(self.details),
        }

    @classmethod
    def from_exception(
        cls,
        exc: Exception,
        *,
        code: str = "runtime_error",
    ) -> ErrorDetail:
        return cls(code=code, message=str(exc), details={"type": exc.__class__.__name__})


@dataclass(frozen=True)
class Result(Generic[T]):
    ok: bool
    value: T | None = None
    error: ErrorDetail | None = None
    warnings: list[str] = field(default_factory=list)

    @classmethod
    def success(
        cls,
        value: T | None = None,
        *,
        warnings: list[str] | None = None,
    ) -> Result[T]:
        return cls(ok=True, value=value, warnings=list(warnings or []))

    @classmethod
    def failure(
        cls,
        code: str,
        message: str,
        *,
        details: dict[str, Any] | None = None,
    ) -> Result[T]:
        return cls(
            ok=False,
            error=ErrorDetail(code=code, message=message, details=dict(details or {})),
        )

    def unwrap(self) -> T:
        if self.ok:
            return self.value  # type: ignore[return-value]
        from framework.shared.errors import RuntimeExecutionError

        error = self.error or ErrorDetail(code="runtime_error", message="result failed")
        raise RuntimeExecutionError(error.message, code=error.code, details=error.details)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "value": to_jsonable(self.value),
            "error": self.error.to_dict() if self.error is not None else None,
            "warnings": list(self.warnings),
        }
