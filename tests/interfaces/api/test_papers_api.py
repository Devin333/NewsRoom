import json
import time
from datetime import datetime, timedelta, timezone
from threading import Event

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
    monkeypatch.setenv("NEWSROOM_PAPERS_AI_SUMMARY_CACHE_PATH", str(tmp_path / "summaries.json"))
    monkeypatch.setenv("NEWSROOM_PAPERS_SUMMARY_EVENTS_PATH", str(tmp_path / "summary-events.jsonl"))

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
    fresh_published_at = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat().replace("+00:00", "Z")
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
                        "publishedAt": fresh_published_at,
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
    refreshed = client.post("/api/v1/papers/paper-summary/summary?locale=en&refresh=true")

    assert first.status_code == 200
    assert first.json()["data"]["summary"]["summary"] == "A concise real LLM summary."
    assert first.json()["data"]["summary"]["cached"] is False
    assert second.status_code == 200
    assert second.json()["data"]["summary"]["cached"] is True
    assert refreshed.status_code == 200
    assert refreshed.json()["data"]["summary"]["cached"] is False
    assert FakeClient.calls == 2


def test_papers_summary_api_returns_cached_fallback_when_model_is_unavailable(monkeypatch, tmp_path) -> None:
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
    monkeypatch.setenv("NEWSROOM_PAPERS_AI_SUMMARY_CACHE_PATH", str(tmp_path / "fallback-summaries.json"))
    monkeypatch.setenv("NEWSROOM_PAPERS_SUMMARY_EVENTS_PATH", str(tmp_path / "fallback-events.jsonl"))

    class FailingClient:
        def complete(self, request):
            raise RuntimeError("provider unavailable")

    def factory() -> PapersApplicationService:
        return PapersApplicationService(llm_client_factory=lambda route: FailingClient())

    client = TestClient(create_app(papers_service_factory=factory, audit_emitter_factory=None))
    response = client.post("/api/v1/papers/paper-summary-error/summary?locale=en")

    assert response.status_code == 200
    summary = response.json()["data"]["summary"]
    assert summary["summary"].startswith("Summary Error Paper is a research paper")
    assert summary["cached"] is False
    assert summary["summarySchemaVersion"] == "v2"


def test_papers_ops_stats_api_returns_safe_reader_runtime_stats(monkeypatch, tmp_path) -> None:
    cache_path = tmp_path / "papers.json"
    summary_path = tmp_path / "ai-summaries.json"
    events_path = tmp_path / "summary-events.jsonl"
    reader_cache_dir = tmp_path / "reader-cache"
    text_extraction_dir = tmp_path / "text-extractions"
    cache_path.write_text(
        json.dumps(
            {
                "source": "api-cache",
                "collectedAt": "2026-05-24T13:41:06Z",
                "papers": [
                    {
                        "id": "ops-api-paper",
                        "title": "Ops API Paper",
                        "abstractSnippet": "A paper for ops API stats.",
                        "authors": ["Alice Example"],
                        "publishedAt": "2026-05-24T00:00:00Z",
                        "paperUrl": "https://arxiv.org/abs/2605.00020",
                        "isPublished": True,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    summary_path.write_text(
        json.dumps(
            {
                "ops-api-paper:hash:en:writer-primary:v2": {
                    "paperId": "ops-api-paper",
                    "locale": "en",
                    "modelRoute": "writer-primary",
                    "abstractHash": "hash",
                    "summary": "Cached summary.",
                    "keyInsights": [],
                    "limitations": [],
                    "summarySchemaVersion": "v2",
                    "generatedAt": "2026-05-25T00:00:00Z",
                    "raw_payload": {"token": "secret"},
                }
            }
        ),
        encoding="utf-8",
    )
    events_path.write_text(
        json.dumps(
            {
                "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                "paperId": "ops-api-paper",
                "locale": "en",
                "modelRoute": "writer-primary",
                "outcome": "generated",
                "durationMs": 42,
                "cacheHit": False,
                "schemaVersion": "v2",
                "secret": "should not leak",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    reader_cache_dir.mkdir()
    text_extraction_dir.mkdir()
    (reader_cache_dir / "ops-api-paper.json").write_text("{}", encoding="utf-8")
    (text_extraction_dir / "ops-api-paper.json").write_text("{}", encoding="utf-8")
    monkeypatch.setenv("NEWSROOM_PAPERS_DATA_PATH", str(cache_path))
    monkeypatch.setenv("NEWSROOM_PAPERS_AI_SUMMARY_CACHE_PATH", str(summary_path))
    monkeypatch.setenv("NEWSROOM_PAPERS_SUMMARY_EVENTS_PATH", str(events_path))
    monkeypatch.setenv("NEWSROOM_PAPERS_READER_CACHE_DIR", str(reader_cache_dir))
    monkeypatch.setenv("NEWSROOM_PAPERS_TEXT_EXTRACTION_DIR", str(text_extraction_dir))

    client = TestClient(create_app(audit_emitter_factory=None))
    response = client.get("/api/v1/papers/ops/stats?windowHours=24")
    payload = response.json()

    assert response.status_code == 200
    assert payload["success"] is True
    stats = payload["data"]["stats"]
    assert stats["paperCache"]["paperCount"] == 1
    assert stats["summaryCache"]["v2EntryCount"] == 1
    assert stats["summaryEvents"]["generatedCount"] == 1
    assert stats["readerCache"]["fileCount"] == 1
    assert stats["textExtraction"]["fileCount"] == 1
    serialized = json.dumps(stats)
    assert "secret" not in serialized
    assert str(tmp_path) not in serialized


def test_papers_ask_api_returns_grounded_answer_and_not_found(monkeypatch, tmp_path) -> None:
    cache_path = tmp_path / "papers.json"
    cache_path.write_text(
        json.dumps(
            {
                "papers": [
                    {
                        "id": "paper-ask",
                        "slug": "paper-ask",
                        "title": "Askable Paper",
                        "abstractSnippet": "This paper studies agent memory and tool use for research workflows.",
                        "authors": ["A"],
                        "publishedAt": "2026-05-24T00:00:00Z",
                        "paperUrl": "https://arxiv.org/abs/2605.00008",
                        "isPublished": True,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("NEWSROOM_PAPERS_DATA_PATH", str(cache_path))

    client = TestClient(create_app(audit_emitter_factory=None))
    response = client.post("/api/v1/papers/paper-ask/ask", json={"question": "What does it study?", "locale": "en"})
    missing = client.post("/api/v1/papers/missing/ask", json={"question": "What does it study?", "locale": "en"})

    assert response.status_code == 200
    answer = response.json()["data"]["answer"]
    assert "agent memory" in answer["answer"]
    assert answer["citations"][0]["sectionId"] == "paper-ask:abstract"
    assert answer["confidence"] > 0
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "paper_not_found"


def test_papers_reader_api_surfaces_sections_related_graph_tasks_and_methods(monkeypatch, tmp_path) -> None:
    cache_path = tmp_path / "papers.json"
    cache_path.write_text(
        json.dumps(
            {
                "papers": [
                    {
                        "id": "surface-paper",
                        "slug": "surface-paper",
                        "title": "Surface Paper",
                        "abstractSnippet": "Paper about API surfaces for reader agents.",
                        "authors": ["A"],
                        "publishedAt": "2026-05-24T00:00:00Z",
                        "paperUrl": "https://arxiv.org/abs/2605.00009",
                        "repoUrl": "https://github.com/owner/surface-paper",
                        "taskRefs": [{"id": "task-api", "slug": "api", "name": "API"}],
                        "methodRefs": [{"id": "method-reader", "slug": "reader-agent", "name": "Reader Agent"}],
                        "evidenceRefs": [
                            {
                                "evidenceId": "ev-blog",
                                "title": "Release note",
                                "sourceType": "official_blog",
                                "url": "https://example.com/release",
                                "raw_payload": {"token": "secret"},
                            }
                        ],
                        "isPublished": True,
                    },
                    {
                        "id": "surface-related",
                        "slug": "surface-related",
                        "title": "Related Surface Paper",
                        "abstractSnippet": "Another reader agent API paper.",
                        "authors": ["B"],
                        "publishedAt": "2026-05-23T00:00:00Z",
                        "paperUrl": "https://arxiv.org/abs/2605.00010",
                        "taskRefs": [{"id": "task-api", "slug": "api", "name": "API"}],
                        "methodRefs": [{"id": "method-reader", "slug": "reader-agent", "name": "Reader Agent"}],
                        "isPublished": True,
                    },
                ]
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("NEWSROOM_PAPERS_DATA_PATH", str(cache_path))

    client = TestClient(create_app(audit_emitter_factory=None))

    sections = client.get("/api/v1/papers/surface-paper/sections")
    related = client.get("/api/v1/papers/surface-paper/related")
    graph = client.get("/api/v1/papers/surface-paper/graph")
    tasks = client.get("/api/v1/papers/tasks")
    methods = client.get("/api/v1/papers/methods")
    missing = client.get("/api/v1/papers/missing/sections")

    assert sections.status_code == 200
    assert sections.json()["data"]["sections"][0]["sectionType"] == "abstract"
    assert related.status_code == 200
    assert related.json()["data"]["relatedPapers"][0]["id"] == "surface-related"
    assert graph.status_code == 200
    serialized_graph = json.dumps(graph.json())
    assert "secret" not in serialized_graph
    assert any(node["type"] == "news" for node in graph.json()["data"]["graph"]["nodes"])
    assert tasks.status_code == 200
    assert tasks.json()["data"]["tasks"][0]["slug"] == "api"
    assert tasks.json()["data"]["tasks"][0]["paperCount"] == 2
    assert methods.status_code == 200
    assert methods.json()["data"]["methods"][0]["slug"] == "reader-agent"
    assert methods.json()["data"]["methods"][0]["paperCount"] == 2
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "paper_not_found"


def test_papers_ops_ingest_api_returns_runs_repair_blocked_and_taxonomy() -> None:
    client = TestClient(
        create_app(
            paper_ingest_service_factory=lambda: _FakePaperIngestService(),
            audit_emitter_factory=None,
        )
    )

    response = client.get("/api/v1/papers/ops/ingest")
    runs = client.get("/api/v1/papers/ops/ingest-runs")
    repair = client.get("/api/v1/papers/ops/repair")
    blocked = client.get("/api/v1/papers/ops/blocked")
    taxonomy = client.get("/api/v1/papers/ops/taxonomy-events")

    assert response.status_code == 200
    assert response.json()["data"]["ingest"]["runs"][0]["runId"] == "paper-run-1"
    assert runs.json()["data"]["runs"][0]["publishedCount"] == 1
    assert repair.json()["data"]["items"][0]["queue"] == "agent_repair"
    assert blocked.json()["data"]["items"][0]["queue"] == "manual_blocked"
    assert taxonomy.json()["data"]["events"][0]["slug"] == "agent-planning"


def test_papers_ops_ingest_trigger_enqueues_worker_task() -> None:
    worker = _FakePaperWorkerService()
    client = TestClient(
        create_app(
            worker_service_factory=lambda: worker,
            paper_ingest_service_factory=lambda: _FakePaperIngestService(),
            audit_emitter_factory=None,
        )
    )

    response = client.post(
        "/api/v1/papers/ops/ingest/trigger",
        json={"candidateLimit": 100, "minGithubStars": 50, "runId": "paper-run-2"},
    )

    assert response.status_code == 200
    assert worker.calls == [(100, 50, "paper-run-2")]
    assert response.json()["data"]["enqueued"]["task_type"] == "papers.ingest_github_arxiv_daily"


def test_papers_ops_visual_compile_backfill_trigger_enqueues_worker_task() -> None:
    worker = _FakePaperWorkerService()
    client = TestClient(
        create_app(
            worker_service_factory=lambda: worker,
            audit_emitter_factory=None,
        )
    )

    response = client.post(
        "/api/v1/papers/ops/visual-compile/trigger",
        json={"limit": 25, "force": True, "runId": "reader-backfill-run"},
    )

    assert response.status_code == 200
    assert worker.visual_backfill_calls == [(25, True, "reader-backfill-run")]
    assert response.json()["data"]["enqueued"]["task_type"] == "papers.visual_compile_backfill"


def test_paper_ops_endpoints_require_ops_permission(monkeypatch, tmp_path) -> None:
    cache_path = tmp_path / "papers.json"
    cache_path.write_text(
        json.dumps(
            {
                "papers": [
                    {
                        "id": "ops-permission-paper",
                        "slug": "ops-permission-paper",
                        "title": "Ops Permission Paper",
                        "abstractSnippet": "A paper used to verify paper ops permissions.",
                        "authors": ["A"],
                        "publishedAt": "2026-05-24T00:00:00Z",
                        "paperUrl": "https://arxiv.org/abs/2605.90001",
                        "pdfUrl": "https://arxiv.org/pdf/2605.90001.pdf",
                        "isPublished": True,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("NEWSROOM_PAPERS_DATA_PATH", str(cache_path))
    worker = _FakePaperWorkerService()
    client = TestClient(
        create_app(
            api_keys={
                "read-token": "read-only",
                "dev-token": "developer",
                "operator-token": "operator",
            },
            worker_service_factory=lambda: worker,
            audit_emitter_factory=None,
        )
    )

    read_only = client.post(
        "/api/v1/papers/ops/ingest/trigger",
        headers={"Authorization": "Bearer read-token"},
        json={"runId": "forbidden-read"},
    )
    developer = client.post(
        "/api/v1/papers/ops/ingest/trigger",
        headers={"Authorization": "Bearer dev-token"},
        json={"runId": "forbidden-dev"},
    )
    compile_forbidden = client.post(
        "/api/v1/papers/ops-permission-paper/compile",
        headers={"Authorization": "Bearer dev-token"},
        json={"force": True, "runId": "compile-forbidden"},
    )
    operator = client.post(
        "/api/v1/papers/ops-permission-paper/compile",
        headers={"Authorization": "Bearer operator-token"},
        json={"force": True, "runId": "compile-allowed"},
    )

    assert read_only.status_code == 403
    assert read_only.json()["error"]["details"]["required_permission"] == "papers:ops"
    assert developer.status_code == 403
    assert developer.json()["error"]["details"]["required_permission"] == "papers:ops"
    assert compile_forbidden.status_code == 403
    assert compile_forbidden.json()["error"]["details"]["required_permission"] == "papers:ops"
    assert operator.status_code == 200
    assert worker.visual_compile_calls == [("ops-permission-paper", True, "compile-allowed")]


def test_papers_ops_ingest_trigger_falls_back_to_local_background_when_worker_queue_is_down() -> None:
    worker = _UnavailablePaperWorkerService()
    ingest = _RecordingPaperIngestService()
    visual_compiler = _RecordingPaperVisualCompilerService()
    client = TestClient(
        create_app(
            worker_service_factory=lambda: worker,
            paper_ingest_service_factory=lambda: ingest,
            paper_visual_compiler_service_factory=lambda: visual_compiler,
            audit_emitter_factory=None,
        )
    )

    response = client.post(
        "/api/v1/papers/ops/ingest/trigger",
        json={"candidateLimit": 100, "minGithubStars": 50, "runId": "paper-local-run"},
    )

    payload = response.json()["data"]["enqueued"]
    assert response.status_code == 200
    assert payload["queue_name"] == "local:background"
    assert payload["mode"] == "local_background"
    for _ in range(100):
        if ingest.calls and len(visual_compiler.compile_calls) == 2:
            break
        time.sleep(0.01)
    assert ingest.calls == [(100, 50, "paper-local-run")]
    assert visual_compiler.compile_calls == [
        ("paper-1", False, "paper-local-run"),
        ("paper-2", False, "paper-local-run"),
    ]


def test_papers_ops_local_background_deduplicates_active_ingest_runs(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("NEWSROOM_PAPERS_OPS_STATE_DIR", str(tmp_path / "ops"))
    worker = _UnavailablePaperWorkerService()
    ingest = _BlockingPaperIngestService()
    visual_compiler = _RecordingPaperVisualCompilerService()
    client = TestClient(
        create_app(
            worker_service_factory=lambda: worker,
            paper_ingest_service_factory=lambda: ingest,
            paper_visual_compiler_service_factory=lambda: visual_compiler,
            audit_emitter_factory=None,
        )
    )

    first = client.post(
        "/api/v1/papers/ops/ingest/trigger",
        json={"candidateLimit": 100, "minGithubStars": 50, "runId": "paper-local-active-1"},
    )
    assert first.status_code == 200
    assert ingest.started.wait(timeout=2)

    second = client.post(
        "/api/v1/papers/ops/ingest/trigger",
        json={"candidateLimit": 100, "minGithubStars": 50, "runId": "paper-local-active-2"},
    )
    ingest.release.set()

    for _ in range(100):
        if ingest.finished.is_set():
            break
        time.sleep(0.01)

    assert second.status_code == 200
    assert second.json()["data"]["enqueued"]["already_running"] is True
    assert second.json()["data"]["enqueued"]["run_id"] == "paper-local-active-1"
    assert ingest.calls == [(100, 50, "paper-local-active-1")]


def test_papers_ops_classification_backfill_trigger_runs_local_background() -> None:
    ingest = _RecordingPaperIngestService()
    client = TestClient(
        create_app(
            paper_ingest_service_factory=lambda: ingest,
            audit_emitter_factory=None,
        )
    )

    response = client.post(
        "/api/v1/papers/ops/classification-backfill/trigger",
        json={"limit": 10, "batchSize": 5, "runId": "classification-backfill-test"},
    )

    payload = response.json()["data"]["backfill"]
    assert response.status_code == 200
    assert payload["runId"] == "classification-backfill-test"
    assert payload["status"] == "queued"
    assert payload["mode"] == "local_background"
    assert payload["limit"] == 10
    assert payload["batchSize"] == 5
    for _ in range(100):
        if ingest.backfill_calls:
            break
        time.sleep(0.01)
    assert ingest.backfill_calls == [(10, 5, "classification-backfill-test")]


def test_papers_ops_classification_backfill_records_background_result(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("NEWSROOM_PAPERS_OPS_STATE_DIR", str(tmp_path))
    ingest = _RecordingPaperIngestService()
    client = TestClient(
        create_app(
            paper_ingest_service_factory=lambda: ingest,
            audit_emitter_factory=None,
        )
    )

    response = client.post(
        "/api/v1/papers/ops/classification-backfill/trigger",
        json={"limit": 10, "batchSize": 5, "runId": "classification-backfill-recorded"},
    )

    assert response.status_code == 200
    for _ in range(100):
        runs_payload = json.loads((tmp_path / "ops-runs.json").read_text(encoding="utf-8"))
        run = runs_payload["runs"][0]
        if run["status"] == "succeeded":
            break
        time.sleep(0.01)

    runs_payload = json.loads((tmp_path / "ops-runs.json").read_text(encoding="utf-8"))
    run = runs_payload["runs"][0]
    assert run["runId"] == "classification-backfill-recorded"
    assert run["status"] == "succeeded"
    assert run["batchSize"] == 5
    assert run["scannedCount"] == 0
    assert run["updatedPaperIds"] == []


def test_papers_ops_citation_backfill_trigger_runs_local_background() -> None:
    ingest = _RecordingPaperIngestService()
    client = TestClient(
        create_app(
            paper_ingest_service_factory=lambda: ingest,
            audit_emitter_factory=None,
        )
    )

    response = client.post(
        "/api/v1/papers/ops/citation-backfill/trigger",
        json={"limit": 10, "batchSize": 5, "runId": "citation-backfill-test"},
    )

    payload = response.json()["data"]["backfill"]
    assert response.status_code == 200
    assert payload["runId"] == "citation-backfill-test"
    assert payload["status"] == "queued"
    assert payload["mode"] == "local_background"
    assert payload["limit"] == 10
    assert payload["batchSize"] == 5
    for _ in range(100):
        if ingest.citation_backfill_calls:
            break
        time.sleep(0.01)
    assert ingest.citation_backfill_calls == [(10, 5, "citation-backfill-test")]


class _FakePaperIngestService:
    def get_ops_state(self, *, limit: int = 20):
        return {
            "runs": [
                {
                    "runId": "paper-run-1",
                    "status": "partial",
                    "startedAt": "2026-05-27T00:00:00Z",
                    "finishedAt": "2026-05-27T00:01:00Z",
                    "candidateLimit": 100,
                    "minGithubStars": 50,
                    "candidateCount": 2,
                    "processedCount": 2,
                    "publishedCount": 1,
                    "skippedNoGithubCount": 0,
                    "skippedLowStarsCount": 0,
                    "repairQueuedCount": 1,
                    "blockedCount": 1,
                    "failureCount": 1,
                    "publishedPaperIds": ["paper-1"],
                }
            ],
            "repairQueue": [
                {
                    "itemId": "repair-1",
                    "runId": "paper-run-1",
                    "paperId": "paper-2",
                    "step": "classify",
                    "errorCode": "classifier_json_invalid",
                    "errorMessage": "bad json",
                    "status": "queued",
                    "queue": "agent_repair",
                    "createdAt": "2026-05-27T00:00:00Z",
                }
            ],
            "blockedItems": [
                {
                    "itemId": "blocked-1",
                    "runId": "paper-run-1",
                    "paperId": "paper-3",
                    "step": "classify",
                    "errorCode": "classifier_unavailable",
                    "errorMessage": "missing API key",
                    "status": "blocked",
                    "queue": "manual_blocked",
                    "createdAt": "2026-05-27T00:00:00Z",
                }
            ],
            "taxonomyEvents": [
                {
                    "eventId": "tax-1",
                    "runId": "paper-run-1",
                    "paperId": "paper-1",
                    "kind": "task",
                    "slug": "agent-planning",
                    "name": "Agent Planning",
                    "confidence": 0.9,
                    "action": "auto_published",
                    "createdAt": "2026-05-27T00:00:00Z",
                }
            ],
            "promptMemory": [],
            "config": {
                "candidateLimit": 100,
                "minGithubStars": 50,
                "autoTaxonomyConfidence": 0.85,
                "arxivQuery": "cat:cs.AI",
                "classifierModelRoute": "writer-primary",
            },
        }

    def backfill_published_classification(self, *, limit=None, batch_size=25, run_id=None):
        class Result:
            def to_dict(self):
                return {
                    "runId": run_id,
                    "batchSize": batch_size,
                    "scannedCount": 0,
                    "updatedCount": 0,
                    "skippedCount": 0,
                    "repairQueuedCount": 0,
                    "blockedCount": 0,
                    "updatedPaperIds": [],
                    "errors": [],
                }

        return Result()

    def backfill_published_citations(self, *, limit=None, batch_size=50, run_id=None):
        class Result:
            def to_dict(self):
                return {
                    "runId": run_id,
                    "batchSize": batch_size,
                    "scannedCount": 0,
                    "updatedCount": 0,
                    "skippedCount": 0,
                    "repairQueuedCount": 0,
                    "blockedCount": 0,
                    "updatedPaperIds": [],
                    "errors": [],
                }

        return Result()


class _FakePaperWorkerService:
    def __init__(self) -> None:
        self.calls = []
        self.visual_backfill_calls = []
        self.visual_compile_calls = []

    def enqueue_paper_ingest(self, *, candidate_limit=None, min_github_stars=None, run_id=None):
        self.calls.append((candidate_limit, min_github_stars, run_id))

        class Result:
            def to_dict(self):
                return {
                    "message_id": "1-0",
                    "task_id": "task-1",
                    "task_type": "papers.ingest_github_arxiv_daily",
                    "queue_name": "news:queue:papers",
                    "status": "queued",
                }

        return Result()

    def enqueue_paper_visual_compile_backfill(self, *, limit=None, force=False, run_id=None):
        self.visual_backfill_calls.append((limit, force, run_id))

        class Result:
            def to_dict(self):
                return {
                    "message_id": "2-0",
                    "task_id": "task-reader-backfill",
                    "task_type": "papers.visual_compile_backfill",
                    "queue_name": "news:queue:papers",
                    "status": "queued",
                    "limit": limit,
                    "force": force,
                    "run_id": run_id,
                }

        return Result()

    def enqueue_paper_visual_compile(self, *, paper_id, force=False, run_id=None):
        self.visual_compile_calls.append((paper_id, force, run_id))

        class Result:
            def to_dict(self):
                return {
                    "message_id": "3-0",
                    "task_id": "task-reader-compile",
                    "task_type": "papers.visual_compile",
                    "queue_name": "news:queue:papers",
                    "status": "queued",
                    "paper_id": paper_id,
                    "force": force,
                    "run_id": run_id,
                }

        return Result()


class _UnavailablePaperWorkerService:
    def enqueue_paper_ingest(self, *, candidate_limit=None, min_github_stars=None, run_id=None):
        raise ConnectionError("Redis connection refused on 127.0.0.1:6379")

    def enqueue_paper_visual_compile_backfill(self, *, limit=None, force=False, run_id=None):
        raise ConnectionError("Redis connection refused on 127.0.0.1:6379")


class _RecordingPaperIngestService(_FakePaperIngestService):
    def __init__(self) -> None:
        self.calls = []
        self.backfill_calls = []
        self.citation_backfill_calls = []

    def run_daily_ingest(self, *, candidate_limit=None, min_github_stars=None, run_id=None):
        self.calls.append((candidate_limit, min_github_stars, run_id))

        class Result:
            def to_dict(self):
                return {
                    "runId": run_id,
                    "status": "succeeded",
                    "publishedPaperIds": ["paper-1", "paper-2"],
                }

        return Result()

    def backfill_published_classification(self, *, limit=None, batch_size=25, run_id=None):
        self.backfill_calls.append((limit, batch_size, run_id))

        class Result:
            def to_dict(self):
                return {
                    "runId": run_id,
                    "batchSize": batch_size,
                    "scannedCount": 0,
                    "updatedCount": 0,
                    "skippedCount": 0,
                    "repairQueuedCount": 0,
                    "blockedCount": 0,
                    "updatedPaperIds": [],
                    "errors": [],
                }

        return Result()

    def backfill_published_citations(self, *, limit=None, batch_size=50, run_id=None):
        self.citation_backfill_calls.append((limit, batch_size, run_id))

        class Result:
            def to_dict(self):
                return {
                    "runId": run_id,
                    "batchSize": batch_size,
                    "scannedCount": 0,
                    "updatedCount": 0,
                    "skippedCount": 0,
                    "repairQueuedCount": 0,
                    "blockedCount": 0,
                    "updatedPaperIds": [],
                    "errors": [],
                }

        return Result()


class _BlockingPaperIngestService(_FakePaperIngestService):
    def __init__(self) -> None:
        self.calls = []
        self.started = Event()
        self.release = Event()
        self.finished = Event()

    def run_daily_ingest(self, *, candidate_limit=None, min_github_stars=None, run_id=None):
        self.calls.append((candidate_limit, min_github_stars, run_id))
        self.started.set()
        self.release.wait(timeout=2)
        self.finished.set()

        class Result:
            def to_dict(self):
                return {
                    "runId": run_id,
                    "publishedPaperIds": [],
                    "publishedCount": 0,
                    "blockedCount": 0,
                    "errors": [],
                }

        return Result()


class _RecordingPaperVisualCompilerService:
    def __init__(self) -> None:
        self.compile_calls = []

    def compile_paper(self, paper_id, *, force=False, run_id=None):
        self.compile_calls.append((paper_id, force, run_id))

        class Result:
            def to_dict(self):
                return {
                    "paperId": paper_id,
                    "status": "compiled",
                }

        return Result()
