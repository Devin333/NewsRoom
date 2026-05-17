from __future__ import annotations

import json
import socket
import urllib.error
import urllib.parse
import urllib.request
import uuid
from dataclasses import dataclass
from typing import Any, Callable, Protocol

from newsroom_sdk.config import NewsRoomConfig
from newsroom_sdk.errors import (
    NewsRoomAPIError,
    NewsRoomConnectionError,
    NewsRoomResponseError,
    NewsRoomTimeoutError,
)
from newsroom_sdk.models import JsonDict


class RequestFunc(Protocol):
    def __call__(
        self,
        method: str,
        path: str,
        *,
        headers: dict[str, str],
        json: JsonDict | None = None,
        params: JsonDict | None = None,
        timeout: float | None = None,
    ) -> Any:
        ...


@dataclass(frozen=True)
class _TransportResponse:
    status_code: int
    payload: JsonDict


class HttpTransport:
    def __init__(
        self,
        config: NewsRoomConfig,
        *,
        request_func: RequestFunc | None = None,
    ) -> None:
        self.config = config
        self.request_func = request_func

    def request(
        self,
        method: str,
        path: str,
        *,
        json: JsonDict | None = None,
        params: JsonDict | None = None,
    ) -> JsonDict:
        response = self._raw_request(method, path, json=json, params=params)
        return self._unwrap_envelope(response)

    def _raw_request(
        self,
        method: str,
        path: str,
        *,
        json: JsonDict | None = None,
        params: JsonDict | None = None,
    ) -> _TransportResponse:
        headers = self._headers(has_json_body=json is not None)
        try:
            if self.request_func is not None:
                return self._from_injected_response(
                    self.request_func(
                        method,
                        path,
                        headers=headers,
                        json=json,
                        params=params,
                        timeout=self.config.timeout,
                    )
                )
            return self._urllib_request(method, path, headers=headers, json_body=json, params=params)
        except TimeoutError as exc:
            raise NewsRoomTimeoutError(str(exc)) from exc
        except socket.timeout as exc:
            raise NewsRoomTimeoutError(str(exc)) from exc
        except urllib.error.URLError as exc:
            reason = getattr(exc, "reason", exc)
            if isinstance(reason, TimeoutError):
                raise NewsRoomTimeoutError(str(reason)) from exc
            raise NewsRoomConnectionError(str(reason)) from exc

    def _urllib_request(
        self,
        method: str,
        path: str,
        *,
        headers: dict[str, str],
        json_body: JsonDict | None,
        params: JsonDict | None,
    ) -> _TransportResponse:
        request = urllib.request.Request(
            _url(self.config.base_url, path, params=params),
            data=_json_bytes(json_body) if json_body is not None else None,
            method=method.upper(),
            headers=headers,
        )
        try:
            with urllib.request.urlopen(request, timeout=self.config.timeout) as response:
                return _TransportResponse(
                    status_code=int(getattr(response, "status", 200)),
                    payload=_decode_json_payload(response.read()),
                )
        except urllib.error.HTTPError as exc:
            body = exc.read()
            return _TransportResponse(status_code=exc.code, payload=_decode_json_payload(body))

    def _from_injected_response(self, response: Any) -> _TransportResponse:
        if isinstance(response, dict):
            return _TransportResponse(status_code=200, payload=dict(response))
        status_code = int(getattr(response, "status_code", getattr(response, "status", 200)))
        try:
            payload = response.json()
        except AttributeError:
            payload = _decode_json_payload(response.read())
        except ValueError as exc:
            raise NewsRoomResponseError("response body is not valid JSON") from exc
        if not isinstance(payload, dict):
            raise NewsRoomResponseError("response body must be a JSON object")
        return _TransportResponse(status_code=status_code, payload=payload)

    def _unwrap_envelope(self, response: _TransportResponse) -> JsonDict:
        payload = response.payload
        if payload.get("success") is True:
            data = payload.get("data")
            return dict(data or {})
        if payload.get("success") is False:
            error = payload.get("error") or {}
            raise NewsRoomAPIError(
                code=str(error.get("code") or "api_error"),
                message=str(error.get("message") or "API request failed"),
                status_code=response.status_code,
                details=dict(error.get("details") or {}),
                retryable=bool(error.get("retryable")),
                user_action_required=bool(error.get("user_action_required")),
                request_id=_optional_str(error.get("request_id") or payload.get("request_id")),
            )
        raise NewsRoomResponseError("response is missing the NewsRoom API envelope")

    def _headers(self, *, has_json_body: bool) -> dict[str, str]:
        headers = {
            "Accept": "application/json",
            "X-Request-ID": uuid.uuid4().hex,
        }
        if has_json_body:
            headers["Content-Type"] = "application/json"
        if self.config.api_key:
            headers["Authorization"] = f"Bearer {self.config.api_key}"
        return headers


def quote_path_segment(value: str) -> str:
    return urllib.parse.quote(value, safe="")


def _url(base_url: str, path: str, *, params: JsonDict | None) -> str:
    suffix = path if path.startswith("/") else f"/{path}"
    query = {
        key: value
        for key, value in (params or {}).items()
        if value is not None
    }
    if not query:
        return f"{base_url}{suffix}"
    return f"{base_url}{suffix}?{urllib.parse.urlencode(query, doseq=True)}"


def _json_bytes(payload: JsonDict | None) -> bytes:
    return json.dumps(payload or {}, ensure_ascii=False).encode("utf-8")


def _decode_json_payload(body: bytes) -> JsonDict:
    try:
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise NewsRoomResponseError("response body is not valid JSON") from exc
    if not isinstance(payload, dict):
        raise NewsRoomResponseError("response body must be a JSON object")
    return payload


def _optional_str(value: Any) -> str | None:
    return str(value) if value is not None else None
