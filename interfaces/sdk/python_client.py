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
        retryable: bool = False,
        user_action_required: bool = False,
        request_id: str | None = None,
    ) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message
        self.status_code = status_code
        self.details = details or {}
        self.retryable = retryable
        self.user_action_required = user_action_required
        self.request_id = request_id


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
        self.mcp = MCPClient(self)
        self.workers = WorkersClient(self)
        self.storage = StorageClient(self)
        self.sources = SourcesClient(self)
        self.schedules = SchedulesClient(self)
        self.waits = GraphWaitsClient(self)
        self.research = ResearchClient(self)

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
                retryable=bool(error.get("retryable")),
                user_action_required=bool(error.get("user_action_required")),
                request_id=_optional_str(error.get("request_id") or payload.get("request_id")),
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
    _PREFIX = "/api/v2/graph-runs"

    def __init__(self, client: NewsClient) -> None:
        self.client = client

    def get(self, run_id: str) -> dict[str, Any]:
        return self.client.get(f"{self._PREFIX}/{_quote_path_segment(run_id)}")

    def list(
        self,
        *,
        limit: int = 20,
        offset: int = 0,
        status: str | None = None,
        graph_id: str | None = None,
    ) -> dict[str, Any]:
        return self.client.get(
            self._PREFIX,
            params={
                "limit": limit,
                "offset": offset,
                "status": status,
                "graph_id": graph_id,
            },
        )

    def manifest(self, run_id: str) -> dict[str, Any]:
        return self.client.get(f"{self._PREFIX}/{_quote_path_segment(run_id)}/manifest")

    def events(
        self,
        run_id: str,
        *,
        event_type: str | None = None,
        node_instance_id: str | None = None,
        limit: int | None = None,
        offset: int = 0,
        sequence_cursor: str | None = None,
    ) -> dict[str, Any]:
        return self.client.get(
            f"{self._PREFIX}/{_quote_path_segment(run_id)}/events",
            params={
                "event_type": event_type,
                "node_instance_id": node_instance_id,
                "limit": limit,
                "offset": offset,
                "sequence_cursor": sequence_cursor,
            },
        )

    def replay(self, run_id: str) -> dict[str, Any]:
        return self.client.get(f"{self._PREFIX}/{_quote_path_segment(run_id)}/replay")

    def diagnostics(self, run_id: str) -> dict[str, Any]:
        return self.client.get(f"{self._PREFIX}/{_quote_path_segment(run_id)}/diagnostics")

    def health(self, run_id: str) -> dict[str, Any]:
        return self.client.get(f"{self._PREFIX}/{_quote_path_segment(run_id)}/health")

    def graph(self, run_id: str, *, verify_history: bool = False) -> dict[str, Any]:
        return self.client.get(
            f"{self._PREFIX}/{_quote_path_segment(run_id)}/graph",
            params={"verify_history": verify_history},
        )

    def graph_health(self, run_id: str) -> dict[str, Any]:
        return self.client.get(
            f"{self._PREFIX}/{_quote_path_segment(run_id)}/graph/health"
        )

    def catalog_health(self) -> dict[str, Any]:
        return self.client.get(f"{self._PREFIX}/catalog/health")

    def compare(self, base_run_id: str, target_run_id: str) -> dict[str, Any]:
        return self.client.get(
            f"{self._PREFIX}/compare",
            params={
                "base_run_id": base_run_id,
                "target_run_id": target_run_id,
            },
        )

    def lineage(self, run_id: str) -> dict[str, Any]:
        return self.client.get(f"{self._PREFIX}/{_quote_path_segment(run_id)}/lineage")

    def lineage_upstream(self, run_id: str, *, target_type: str, target_id: str) -> dict[str, Any]:
        return self.client.get(
            f"{self._PREFIX}/{_quote_path_segment(run_id)}/lineage/upstream",
            params={"target_type": target_type, "target_id": target_id},
        )

    def lineage_downstream(self, run_id: str, *, source_type: str, source_id: str) -> dict[str, Any]:
        return self.client.get(
            f"{self._PREFIX}/{_quote_path_segment(run_id)}/lineage/downstream",
            params={"source_type": source_type, "source_id": source_id},
        )

    def artifacts(self, run_id: str) -> dict[str, Any]:
        return self.client.get(f"{self._PREFIX}/{_quote_path_segment(run_id)}/artifacts")

    def artifact(self, run_id: str, artifact_key: str) -> dict[str, Any]:
        return self.client.get(
            f"{self._PREFIX}/{_quote_path_segment(run_id)}/artifacts/{_quote_path_segment(artifact_key)}"
        )

    def cancel(
        self,
        run_id: str,
        *,
        reason_code: str,
        cancellation_id: str | None = None,
    ) -> dict[str, Any]:
        return self.client.post(
            f"{self._PREFIX}/{_quote_path_segment(run_id)}/cancel",
            json_body={
                "reason_code": reason_code,
                "cancellation_id": cancellation_id,
            },
        )


class ReportsClient:
    def __init__(self, client: NewsClient) -> None:
        self.client = client

    def latest(self) -> dict[str, Any]:
        return self.client.get("/api/v1/reports/latest")

    def get(self, report_id: str) -> dict[str, Any]:
        return self.client.get(f"/api/v1/reports/{urllib.parse.quote(report_id)}")

    def search(self, query: str, *, limit: int = 20) -> dict[str, Any]:
        return self.client.get("/api/v1/search/reports", params={"q": query, "limit": limit})

    def list(
        self,
        *,
        limit: int = 20,
        graph_id: str | None = None,
        graph_ids: list[str] | None = None,
    ) -> dict[str, Any]:
        return self.client.get(
            "/api/v1/reports",
            params={"limit": limit, "graph_id": graph_id, "graph_ids": graph_ids},
        )

    def markdown(self, report_id: str) -> dict[str, Any]:
        return self.client.get(f"/api/v1/reports/{_quote_path_segment(report_id)}/markdown")

    def quality(self, report_id: str) -> dict[str, Any]:
        return self.client.get(f"/api/v1/reports/{_quote_path_segment(report_id)}/quality")


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

    def get(self, document_id: str, *, collection: str = "report_sections") -> dict[str, Any]:
        return self.client.get(
            f"/api/v1/memory/{_quote_path_segment(document_id)}",
            params={"collection": collection},
        )

    def reindex(self, run_id: str, *, topic: str | None = None) -> dict[str, Any]:
        return self.client.post(
            "/api/v1/memory/reindex",
            json_body={"run_id": run_id, "topic": topic},
        )


class MCPClient:
    def __init__(self, client: NewsClient) -> None:
        self.client = client

    def catalog(self) -> dict[str, Any]:
        return self.client.get("/api/v1/mcp/catalog")

    def capabilities(self) -> dict[str, Any]:
        return self.client.get("/api/v1/mcp/capabilities")


class WorkersClient:
    def __init__(self, client: NewsClient) -> None:
        self.client = client

    def list(self, *, stale_after_seconds: int = 60) -> dict[str, Any]:
        return self.client.get(
            "/api/v1/workers",
            params={"stale_after_seconds": stale_after_seconds},
        )

    def get(self, worker_id: str, *, stale_after_seconds: int = 60) -> dict[str, Any]:
        return self.client.get(
            f"/api/v1/workers/{_quote_path_segment(worker_id)}",
            params={"stale_after_seconds": stale_after_seconds},
        )

    def queues(self, *, queue_names: list[str] | None = None) -> dict[str, Any]:
        return self.client.get("/api/v1/queues", params={"queue_name": queue_names or []})


class StorageClient:
    def __init__(self, client: NewsClient) -> None:
        self.client = client

    def metrics(self) -> dict[str, Any]:
        return self.client.get("/api/v1/storage/metrics")

    def retention_plan(
        self,
        *,
        run_id: str | None = None,
        now: str | None = None,
        raw_source_retention_days: int | None = None,
        llm_artifact_retention_days: int | None = None,
        run_artifact_retention_days: int | None = None,
        report_retention_days: int | None = None,
        evidence_retention_days: int | None = None,
        vector_retention_days: int | None = None,
    ) -> dict[str, Any]:
        return self.client.get(
            "/api/v1/storage/retention/plan",
            params={
                "run_id": run_id,
                "now": now,
                "raw_source_retention_days": raw_source_retention_days,
                "llm_artifact_retention_days": llm_artifact_retention_days,
                "run_artifact_retention_days": run_artifact_retention_days,
                "report_retention_days": report_retention_days,
                "evidence_retention_days": evidence_retention_days,
                "vector_retention_days": vector_retention_days,
            },
        )


class SourcesClient:
    def __init__(self, client: NewsClient) -> None:
        self.client = client

    def list(self, *, include_disabled: bool = False) -> dict[str, Any]:
        return self.client.get(
            "/api/v1/sources",
            params={"include_disabled": include_disabled},
        )

    def health(self, *, include_disabled: bool = False) -> dict[str, Any]:
        return self.client.get(
            "/api/v1/sources/health",
            params={"include_disabled": include_disabled},
        )

    def validation(self) -> dict[str, Any]:
        return self.client.get("/api/v1/sources/validation")

    def get(self, source_id: str) -> dict[str, Any]:
        return self.client.get(f"/api/v1/sources/{_quote_path_segment(source_id)}")

    def probe(
        self,
        source_id: str,
        *,
        force: bool = False,
        include_disabled: bool = False,
        limit: int = 1,
    ) -> dict[str, Any]:
        return self.client.post(
            f"/api/v1/sources/{_quote_path_segment(source_id)}/probe",
            json_body={
                "force": force,
                "include_disabled": include_disabled,
                "limit": limit,
            },
        )

    def fetch_arxiv(self, query: str, *, limit: int = 5) -> dict[str, Any]:
        return self.client.post(
            "/api/v1/sources/arxiv/fetch",
            json_body={"query": query, "limit": limit},
        )

    def fetch_github_releases(self, repository: str, *, limit: int = 5) -> dict[str, Any]:
        return self.client.post(
            "/api/v1/sources/github/releases",
            json_body={"repository": repository, "limit": limit},
        )


class SchedulesClient:
    def __init__(self, client: NewsClient) -> None:
        self.client = client

    def list(self, *, include_disabled: bool = False) -> dict[str, Any]:
        return self.client.get(
            "/api/v1/schedules",
            params={"include_disabled": include_disabled},
        )

    def upsert_task(
        self,
        *,
        schedule_id: str,
        name: str,
        task_type: str,
        payload_template: dict[str, Any] | None = None,
        trigger_type: str = "interval",
        interval_seconds: int = 86400,
        run_at: str | None = None,
        queue_name: str = "news:queue:memory",
        enabled: bool = True,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self.client.post(
            "/api/v1/schedules",
            json_body={
                "schedule_id": schedule_id,
                "name": name,
                "task_type": task_type,
                "payload_template": payload_template or {},
                "trigger_type": trigger_type,
                "interval_seconds": interval_seconds,
                "run_at": run_at,
                "queue_name": queue_name,
                "enabled": enabled,
                "metadata": metadata or {},
            },
        )

    def trigger(self, schedule_id: str, *, now: str | None = None) -> dict[str, Any]:
        return self.client.post(
            f"/api/v1/schedules/{_quote_path_segment(schedule_id)}/trigger",
            json_body={"now": now},
        )


class GraphWaitsClient:
    def __init__(self, client: NewsClient) -> None:
        self.client = client

    def inspect(self, run_id: str, node_instance_id: str) -> dict[str, Any]:
        return self.client.get(_wait_path(run_id, node_instance_id))

    def deliver_signal(
        self,
        run_id: str,
        node_instance_id: str,
        *,
        signal_id: str,
        signal_schema_ref: str,
        correlation: dict[str, Any],
        payload_ref: str,
    ) -> dict[str, Any]:
        return self.client.post(
            f"{_wait_path(run_id, node_instance_id)}/signals",
            json_body={
                "signal_id": signal_id,
                "signal_schema_ref": signal_schema_ref,
                "correlation": correlation,
                "payload_ref": payload_ref,
            },
        )

    def decide_approval(
        self,
        run_id: str,
        node_instance_id: str,
        *,
        approval_id: str,
        approved: bool,
    ) -> dict[str, Any]:
        return self.client.post(
            f"{_wait_path(run_id, node_instance_id)}/approval",
            json_body={"approval_id": approval_id, "approved": approved},
        )

    def cancel(
        self,
        run_id: str,
        node_instance_id: str,
        *,
        cancellation_id: str,
        reason_code: str,
    ) -> dict[str, Any]:
        return self.client.post(
            f"{_wait_path(run_id, node_instance_id)}/cancel",
            json_body={
                "cancellation_id": cancellation_id,
                "reason_code": reason_code,
            },
        )


def _wait_path(run_id: str, node_instance_id: str) -> str:
    return (
        "/api/v2/graph-runs/"
        f"{_quote_path_segment(run_id)}/waits/"
        f"{_quote_path_segment(node_instance_id)}"
    )

class ResearchClient:
    def __init__(self, client: NewsClient) -> None:
        self.client = client

    def analyze_paper(
        self,
        *,
        paper_id: str,
        source_url: str | None = None,
        pdf_url: str | None = None,
        run_id: str | None = None,
        tenant_id: str | None = None,
        user_id: str | None = None,
        memory_namespace: str | None = None,
        metadata: dict[str, Any] | None = None,
        options: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self.client.post(
            "/api/v1/research/papers/analyze",
            json_body={
                "paperId": paper_id,
                "sourceUrl": source_url,
                "pdfUrl": pdf_url,
                "runId": run_id,
                "userId": user_id,
                "metadata": metadata or {},
                "options": options or {},
                **_research_actor_params(
                    tenant_id=tenant_id,
                    user_id=None,
                    memory_namespace=memory_namespace,
                ),
            },
        )

    def analysis(
        self,
        paper_id: str,
        *,
        tenant_id: str | None = None,
        user_id: str | None = None,
        memory_namespace: str | None = None,
    ) -> dict[str, Any]:
        return self.client.get(
            f"/api/v1/research/papers/{_quote_path_segment(paper_id)}/analysis",
            params=_research_actor_params(
                tenant_id=tenant_id,
                user_id=user_id,
                memory_namespace=memory_namespace,
            ),
        )

    def reader(
        self,
        paper_id: str,
        *,
        tenant_id: str | None = None,
        user_id: str | None = None,
        memory_namespace: str | None = None,
    ) -> dict[str, Any]:
        return self.client.get(
            f"/api/v1/research/papers/{_quote_path_segment(paper_id)}/reader",
            params=_research_actor_params(
                tenant_id=tenant_id,
                user_id=user_id,
                memory_namespace=memory_namespace,
            ),
        )

    def ask(
        self,
        paper_id: str,
        *,
        question: str,
        locale: str | None = None,
        tenant_id: str | None = None,
        user_id: str | None = None,
        memory_namespace: str | None = None,
        selection: dict[str, Any] | None = None,
        options: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self.client.post(
            f"/api/v1/research/papers/{_quote_path_segment(paper_id)}/ask",
            json_body={
                "question": question,
                "locale": locale,
                "selection": selection or {},
                "options": options or {},
                **_research_actor_params(
                    tenant_id=tenant_id,
                    user_id=user_id,
                    memory_namespace=memory_namespace,
                ),
            },
        )

    def trace(
        self,
        run_id: str,
        *,
        tenant_id: str | None = None,
        user_id: str | None = None,
        memory_namespace: str | None = None,
    ) -> dict[str, Any]:
        return self.client.get(
            f"/api/v1/research/runs/{_quote_path_segment(run_id)}/trace",
            params=_research_actor_params(
                tenant_id=tenant_id,
                user_id=user_id,
                memory_namespace=memory_namespace,
            ),
        )


def _research_actor_params(
    *,
    tenant_id: str | None,
    user_id: str | None,
    memory_namespace: str | None,
) -> dict[str, str]:
    return {
        key: value
        for key, value in {
            "tenantId": tenant_id,
            "userId": user_id,
            "memoryNamespace": memory_namespace,
        }.items()
        if value is not None
    }


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


def _quote_path_segment(value: str) -> str:
    return urllib.parse.quote(value, safe="")


def _json_bytes(payload: dict[str, Any] | None) -> bytes:
    return json.dumps(payload or {}, ensure_ascii=False).encode("utf-8")


def _optional_str(value: Any) -> str | None:
    return str(value) if value is not None else None


def _default_opener(request: urllib.request.Request, timeout: int | None):
    return urllib.request.urlopen(request, timeout=timeout)
