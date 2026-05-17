from __future__ import annotations

from enum import Enum
from typing import Any


class ApiErrorCode(str, Enum):
    INVALID_REQUEST = "invalid_request"
    UNAUTHORIZED = "unauthorized"
    FORBIDDEN = "forbidden"
    NOT_FOUND = "not_found"
    WORKFLOW_NOT_FOUND = "workflow_not_found"
    REPORT_NOT_FOUND = "report_not_found"
    RUN_NOT_FOUND = "run_not_found"
    RATE_LIMITED = "rate_limited"
    INTERNAL_ERROR = "internal_error"


def map_exception(exc: Exception) -> tuple[int, ApiErrorCode, str, dict[str, Any]]:
    if isinstance(exc, FileNotFoundError):
        return 404, ApiErrorCode.NOT_FOUND, str(exc), {}
    if isinstance(exc, PermissionError):
        return 403, ApiErrorCode.FORBIDDEN, str(exc), {}
    if isinstance(exc, ValueError):
        return 400, ApiErrorCode.INVALID_REQUEST, str(exc), {}
    return 500, ApiErrorCode.INTERNAL_ERROR, "internal server error", {
        "error_type": type(exc).__name__
    }


def http_error_code(status_code: int) -> str:
    if status_code == 401:
        return ApiErrorCode.UNAUTHORIZED.value
    if status_code == 403:
        return ApiErrorCode.FORBIDDEN.value
    if status_code == 404:
        return ApiErrorCode.NOT_FOUND.value
    if status_code == 409:
        return "conflict"
    if status_code == 429:
        return ApiErrorCode.RATE_LIMITED.value
    if status_code >= 500:
        return ApiErrorCode.INTERNAL_ERROR.value
    return ApiErrorCode.INVALID_REQUEST.value
