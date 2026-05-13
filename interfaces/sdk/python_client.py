from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any, Callable


HttpOpener = Callable[[urllib.request.Request, int | None], Any]


class NewsApiError(RuntimeError):
    def __init__(
        self,
        *,
        code: str,
        message: str,
        status_code: int | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message
        self.status_code = status_code
        self.details = details or {}


@dataclass(frozen=True)
class _Response:
    status_code: int
    payload: dict[str, Any]


class NewsClient:
    def __init__(
        self,
        base_url: str,
        *,
        api_key: str | None = None,
        timeout: int | None = 30,
        opener: HttpOpener | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout
        self._opener = opener or _default_opener
        self.runs = RunsClient(self)
        self.reports = ReportsClient(self)
        self.memory = MemoryClient(self)

    def get(self, path: str, *, params: dict[str, Any] | None = None) -> dict[str, Any]:
        return self._request("GET", path, params=params)

    def post(
        self,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self._request("POST", path, params=params, json_body=json_body)

    def iter_pages(
        self,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        cursor_param: str = "cursor",
    ):
        cursor = (params or {}).get(cursor_param)
        while True:
            page_params = dict(params or {})
            if cursor:
                page_params[cursor_param] = cursor
            data = self.get(path, params=page_params)
            yield data
            cursor = data.get("next_cursor")
            if not cursor:
                break

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        response = self._raw_request(method, path, params=params, json_body=json_body)
        payload = response.payload
        if payload.get("success") is False:
            error = payload.get("error") or {}
            raise NewsApiError(
                code=str(error.get("code") or "api_error"),
                message=str(error.get("message") or "API request failed"),
                status_code=response.status_code,
                details=dict(error.get("details") or {}),
            )
        return dict(payload.get("data") or {})

    def _raw_request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
    ) -> _Response:
        request = urllib.request.Request(
            _url(self.base_url, path, params=params),
            data=_json_bytes(json_body) if json_body is not None else None,
            method=method,
            headers=self._headers(json_body is not None),
        )
        try:
            with self._opener(request, self.timeout) as response:
                status_code = int(getattr(response, "status", 200))
                payload = json.loads(response.read().decode("utf-8"))
                return _Response(status_code=status_code, payload=payload)
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            try:
                payload = json.loads(body)
            except json.JSONDecodeError as parse_error:
                raise NewsApiError(
                    code="http_error",
                    message=body or str(exc),
                    status_code=exc.code,
                ) from parse_error
            return _Response(status_code=exc.code, payload=payload)

    def _headers(self, has_json_body: bool) -> dict[str, str]:
        headers = {"Accept": "application/json"}
        if has_json_body:
            headers["Content-Type"] = "application/json"
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers


class RunsClient:
    def __init__(self, client: NewsClient) -> None:
        self.client = client

    def create_daily(
        self,
        *,
        topic: str = "AI",
        profile: str = "live-offline",
        source_limit: int = 3,
        run_id: str | None = None,
    ) -> dict[str, Any]:
        return self.client.post(
            "/api/v1/runs",
            json_body={
                "workflow_id": "daily",
                "topic": topic,
                "profile": profile,
                "source_limit": source_limit,
                "run_id": run_id,
                "async_run": True,
            },
        )

    def get(self, run_id: str) -> dict[str, Any]:
        return self.client.get(f"/api/v1/runs/{urllib.parse.quote(run_id)}")

    def list(self, *, limit: int = 20) -> dict[str, Any]:
        return self.client.get("/api/v1/runs", params={"limit": limit})


class ReportsClient:
    def __init__(self, client: NewsClient) -> None:
        self.client = client

    def latest(self) -> dict[str, Any]:
        return self.client.get("/api/v1/reports/latest")

    def get(self, report_id: str) -> dict[str, Any]:
        return self.client.get(f"/api/v1/reports/{urllib.parse.quote(report_id)}")

    def search(self, query: str, *, limit: int = 20) -> dict[str, Any]:
        return self.client.get("/api/v1/search/reports", params={"q": query, "limit": limit})


class MemoryClient:
    def __init__(self, client: NewsClient) -> None:
        self.client = client

    def search(
        self,
        query: str,
        *,
        collection: str = "report_sections",
        limit: int = 5,
        filters: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self.client.post(
            "/api/v1/memory/search",
            json_body={
                "query": query,
                "collection": collection,
                "limit": limit,
                "filters": filters or {},
            },
        )


def _url(base_url: str, path: str, *, params: dict[str, Any] | None) -> str:
    query = {
        key: value
        for key, value in (params or {}).items()
        if value is not None
    }
    suffix = path if path.startswith("/") else f"/{path}"
    if not query:
        return f"{base_url}{suffix}"
    return f"{base_url}{suffix}?{urllib.parse.urlencode(query, doseq=True)}"


def _json_bytes(payload: dict[str, Any] | None) -> bytes:
    return json.dumps(payload or {}, ensure_ascii=False).encode("utf-8")


def _default_opener(request: urllib.request.Request, timeout: int | None):
    return urllib.request.urlopen(request, timeout=timeout)
