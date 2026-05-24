import json

from fastapi.testclient import TestClient

from interfaces.api import create_app


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
