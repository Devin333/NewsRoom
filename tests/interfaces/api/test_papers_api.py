import json

from fastapi.testclient import TestClient

from interfaces.api import create_app
from interfaces.services.paper_service import PapersApplicationService


def test_papers_api_returns_real_cached_papers(monkeypatch, tmp_path) -> None:
    cache_path = tmp_path / "papers.json"
    cache_path.write_text(
        json.dumps(
            {
                "source": "arxiv",
                "collectedAt": "2026-05-24T13:41:06Z",
                "papers": [
                    {
                        "id": "arxiv-2605.00001",
                        "slug": "agent-paper",
                        "title": "Agent Paper",
                        "abstractSnippet": "A real collected paper abstract.",
                        "authors": ["Alice Example"],
                        "publishedAt": "2026-05-24T00:00:00Z",
                        "venue": "arXiv",
                        "citationDoi": "10.48550/arxiv.2605.00001",
                        "tags": ["cs.AI"],
                        "paperUrl": "https://arxiv.org/abs/2605.00001",
                        "arxivUrl": "https://arxiv.org/abs/2605.00001",
                        "pdfUrl": "https://arxiv.org/pdf/2605.00001",
                        "isPublished": True,
                    },
                    {
                        "id": "draft-1",
                        "slug": "draft",
                        "title": "Hidden draft",
                        "abstractSnippet": "Not public.",
                        "paperUrl": "https://example.com/draft",
                        "isPublished": False,
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("NEWSROOM_PAPERS_DATA_PATH", str(cache_path))

    client = TestClient(create_app(audit_emitter_factory=None))
    response = client.get("/api/v1/papers?limit=10")
    payload = response.json()

    assert response.status_code == 200
    assert payload["success"] is True
    assert payload["data"]["source"] == "arxiv"
    assert payload["data"]["paper_count"] == 1
    assert payload["data"]["total_count"] == 1
    assert payload["data"]["papers"][0]["title"] == "Agent Paper"
    assert payload["data"]["papers"][0]["pdfUrl"] == "https://arxiv.org/pdf/2605.00001"
    assert "githubStars" not in payload["data"]["papers"][0]


def test_papers_api_filters_query(monkeypatch, tmp_path) -> None:
    cache_path = tmp_path / "papers.json"
    cache_path.write_text(
        json.dumps(
            {
                "papers": [
                    {
                        "id": "paper-1",
                        "title": "Vision Language Navigation",
                        "abstractSnippet": "Robot navigation paper.",
                        "authors": ["A"],
                        "publishedAt": "2026-05-24T00:00:00Z",
                        "tags": ["cs.RO"],
                        "paperUrl": "https://arxiv.org/abs/2605.00001",
                        "isPublished": True,
                    },
                    {
                        "id": "paper-2",
                        "title": "Tokenisation via Convex Relaxations",
                        "abstractSnippet": "NLP tokenisation paper.",
                        "authors": ["B"],
                        "publishedAt": "2026-05-24T00:00:00Z",
                        "tags": ["cs.CL"],
                        "paperUrl": "https://arxiv.org/abs/2605.00002",
                        "isPublished": True,
                    },
                ]
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("NEWSROOM_PAPERS_DATA_PATH", str(cache_path))

    client = TestClient(create_app(audit_emitter_factory=None))
    response = client.get("/api/v1/papers?q=tokenisation")
    payload = response.json()

    assert response.status_code == 200
    assert payload["data"]["paper_count"] == 1
    assert payload["data"]["papers"][0]["id"] == "paper-2"


def test_papers_api_supports_period_sort_task_method_and_pagination(monkeypatch, tmp_path) -> None:
    cache_path = tmp_path / "papers.json"
    cache_path.write_text(
        json.dumps(
            {
                "source": "test-cache",
                "papers": [
                    {
                        "id": "paper-agent-react",
                        "slug": "paper-agent-react",
                        "title": "Agent ReAct Paper",
                        "abstractSnippet": "Agent paper using ReAct.",
                        "authors": ["A"],
                        "publishedAt": "2026-05-24T12:00:00Z",
                        "citationCount": 5,
                        "githubStars": 100,
                        "tags": ["agent"],
                        "taskRefs": [{"id": "task-agents", "slug": "agents", "name": "Agents"}],
                        "methodRefs": [{"id": "method-react", "slug": "react", "name": "ReAct"}],
                        "paperUrl": "https://arxiv.org/abs/2605.00001",
                        "repoUrl": "https://github.com/owner/agent-react",
                        "isPublished": True,
                    },
                    {
                        "id": "paper-old",
                        "slug": "paper-old",
                        "title": "Old Agent Paper",
                        "abstractSnippet": "Old agent paper.",
                        "authors": ["B"],
                        "publishedAt": "2025-01-01T00:00:00Z",
                        "citationCount": 1000,
                        "tags": ["agent"],
                        "taskRefs": [{"id": "task-agents", "slug": "agents", "name": "Agents"}],
                        "methodRefs": [{"id": "method-planning", "slug": "planning", "name": "Planning"}],
                        "paperUrl": "https://arxiv.org/abs/2501.00001",
                        "isPublished": True,
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("NEWSROOM_PAPERS_DATA_PATH", str(cache_path))

    client = TestClient(create_app(audit_emitter_factory=None))
    response = client.get(
        "/api/v1/papers",
        params={
            "period": "weekly",
            "sort": "most_cited",
            "task": "agents",
            "method": "react",
            "limit": 1,
            "offset": 0,
        },
    )
    payload = response.json()

    assert response.status_code == 200
    assert payload["data"]["source"] == "test-cache"
    assert payload["data"]["period"] == "weekly"
    assert payload["data"]["sort"] == "most_cited"
    assert payload["data"]["paper_count"] == 1
    assert payload["data"]["total_count"] == 1
    assert payload["data"]["papers"][0]["id"] == "paper-agent-react"
    assert payload["data"]["papers"][0]["newsroomHeatScore"] > 0


def test_papers_api_extracts_real_github_repo_from_abstract(monkeypatch, tmp_path) -> None:
    cache_path = tmp_path / "papers.json"
    cache_path.write_text(
        json.dumps(
            {
                "papers": [
                    {
                        "id": "paper-github",
                        "title": "Paper With Code",
                        "abstractSnippet": "Code: https://github.com/owner/repo.",
                        "authors": ["A"],
                        "publishedAt": "2026-05-24T00:00:00Z",
                        "paperUrl": "https://arxiv.org/abs/2605.00003",
                        "isPublished": True,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("NEWSROOM_PAPERS_DATA_PATH", str(cache_path))

    client = TestClient(create_app(audit_emitter_factory=None))
    response = client.get("/api/v1/papers")
    payload = response.json()

    assert response.status_code == 200
    assert payload["data"]["papers"][0]["repoUrl"] == "https://github.com/owner/repo"


def test_papers_api_does_not_fabricate_metrics_or_implementation(monkeypatch, tmp_path) -> None:
    cache_path = tmp_path / "papers.json"
    cache_path.write_text(
        json.dumps(
            {
                "papers": [
                    {
                        "id": "paper-no-metrics",
                        "title": "Paper Without Metrics",
                        "abstractSnippet": "A collected paper with no external metrics.",
                        "authors": ["A"],
                        "publishedAt": "2026-05-24T00:00:00Z",
                        "paperUrl": "https://arxiv.org/abs/2605.00004",
                        "isPublished": True,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("NEWSROOM_PAPERS_DATA_PATH", str(cache_path))

    client = TestClient(create_app(audit_emitter_factory=None))
    response = client.get("/api/v1/papers")
    paper = response.json()["data"]["papers"][0]

    assert response.status_code == 200
    assert "repoUrl" not in paper
    assert "githubStars" not in paper
    assert "citationCount" not in paper
    assert paper["implementations"] == []
    assert paper["benchmarks"] == []


def test_papers_api_gets_paper_by_id_or_slug(monkeypatch, tmp_path) -> None:
    cache_path = tmp_path / "papers.json"
    cache_path.write_text(
        json.dumps(
            {
                "papers": [
                    {
                        "id": "paper-detail",
                        "slug": "detail-slug",
                        "title": "Detail Paper",
                        "abstractSnippet": "Detailed abstract.",
                        "authors": ["A"],
                        "publishedAt": "2026-05-24T00:00:00Z",
                        "paperUrl": "https://arxiv.org/abs/2605.00005",
                        "repoUrl": "https://github.com/owner/detail-paper",
                        "isPublished": True,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("NEWSROOM_PAPERS_DATA_PATH", str(cache_path))

    client = TestClient(create_app(audit_emitter_factory=None))
    by_id = client.get("/api/v1/papers/paper-detail")
    by_slug = client.get("/api/v1/papers/detail-slug")
    missing = client.get("/api/v1/papers/missing")

    assert by_id.status_code == 200
    assert by_id.json()["data"]["paper"]["id"] == "paper-detail"
    assert by_id.json()["data"]["paper"]["implementations"][0]["repoUrl"] == "https://github.com/owner/detail-paper"
    assert by_slug.status_code == 200
    assert by_slug.json()["data"]["paper"]["id"] == "paper-detail"
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "paper_not_found"


def test_papers_summary_api_generates_and_caches(monkeypatch, tmp_path) -> None:
    cache_path = tmp_path / "papers.json"
    summary_path = tmp_path / "ai-summaries.json"
    cache_path.write_text(
        json.dumps(
            {
                "papers": [
                    {
                        "id": "paper-summary",
                        "title": "Summary Paper",
                        "abstractSnippet": "A paper abstract for summarisation.",
                        "authors": ["A"],
                        "publishedAt": "2026-05-24T00:00:00Z",
                        "paperUrl": "https://arxiv.org/abs/2605.00006",
                        "isPublished": True,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("NEWSROOM_PAPERS_DATA_PATH", str(cache_path))
    monkeypatch.setenv("NEWSROOM_PAPERS_AI_SUMMARY_CACHE_PATH", str(summary_path))

    class FakeClient:
        calls = 0

        def complete(self, request):
            FakeClient.calls += 1

            class Response:
                content = json.dumps(
                    {
                        "summary": "A concise real LLM summary.",
                        "keyInsights": ["Insight A"],
                        "limitations": ["Limitation A"],
                    }
                )

            return Response()

    def factory() -> PapersApplicationService:
        return PapersApplicationService(llm_client_factory=lambda route: FakeClient())

    client = TestClient(create_app(papers_service_factory=factory, audit_emitter_factory=None))
    first = client.post("/api/v1/papers/paper-summary/summary?locale=en")
    second = client.post("/api/v1/papers/paper-summary/summary?locale=en")

    assert first.status_code == 200
    assert first.json()["data"]["summary"]["summary"] == "A concise real LLM summary."
    assert first.json()["data"]["summary"]["cached"] is False
    assert second.status_code == 200
    assert second.json()["data"]["summary"]["cached"] is True
    assert FakeClient.calls == 1


def test_papers_summary_api_returns_non_blocking_error(monkeypatch, tmp_path) -> None:
    cache_path = tmp_path / "papers.json"
    cache_path.write_text(
        json.dumps(
            {
                "papers": [
                    {
                        "id": "paper-summary-error",
                        "title": "Summary Error Paper",
                        "abstractSnippet": "A paper abstract.",
                        "authors": ["A"],
                        "publishedAt": "2026-05-24T00:00:00Z",
                        "paperUrl": "https://arxiv.org/abs/2605.00007",
                        "isPublished": True,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("NEWSROOM_PAPERS_DATA_PATH", str(cache_path))

    class FailingClient:
        def complete(self, request):
            raise RuntimeError("provider unavailable")

    def factory() -> PapersApplicationService:
        return PapersApplicationService(llm_client_factory=lambda route: FailingClient())

    client = TestClient(create_app(papers_service_factory=factory, audit_emitter_factory=None))
    response = client.post("/api/v1/papers/paper-summary-error/summary?locale=en")

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "paper_summary_unavailable"
    assert response.json()["error"]["retryable"] is True
