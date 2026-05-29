from __future__ import annotations

import re
from contextvars import ContextVar
from typing import Any
from uuid import uuid4

from fastapi.responses import JSONResponse
from pydantic import BaseModel

from framework.tool.governance.redaction import redact_sensitive_values
from interfaces.models import ApiError, ApiResponse


REQUEST_ID_HEADER = "X-Request-ID"
_REQUEST_ID_CONTEXT: ContextVar[str | None] = ContextVar("news_api_request_id", default=None)
_REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9._-]{1,128}$")


def success(data: dict[str, Any] | BaseModel | None = None) -> dict[str, Any]:
    payload = model_to_dict(
        ApiResponse(
            success=True,
            data=model_to_dict(data) if data is not None else None,
            request_id=current_request_id(),
        )
    )
    payload["ok"] = True
    return payload


def error(
    *,
    status_code: int,
    code: str,
    message: str,
    details: dict[str, Any] | None = None,
    retryable: bool = False,
    user_action_required: bool = False,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    request_id = current_request_id()
    payload = ApiResponse(
        success=False,
        error=ApiError(
            code=code,
            message=message,
            details=redact_sensitive_values(details or {}),
            retryable=retryable,
            user_action_required=user_action_required,
            request_id=request_id,
        ),
        request_id=request_id,
    )
    content = model_to_dict(payload)
    content["ok"] = False
    return JSONResponse(status_code=status_code, content=content, headers=headers)


def model_to_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if hasattr(value, "model_dump"):
        return value.model_dump()
    if hasattr(value, "dict"):
        return value.dict()
    raise TypeError(f"cannot convert {type(value).__name__} to dict")


def current_request_id() -> str:
    return _REQUEST_ID_CONTEXT.get() or new_request_id()


def new_request_id() -> str:
    return f"req_{uuid4().hex}"


def request_id_from_header(value: str | None) -> str | None:
    if value is None:
        return None
    request_id = value.strip()
    if not _REQUEST_ID_PATTERN.fullmatch(request_id):
        return None
    return request_id


def set_request_id(request_id: str):
    return _REQUEST_ID_CONTEXT.set(request_id)


def reset_request_id(token: Any) -> None:
    _REQUEST_ID_CONTEXT.reset(token)
