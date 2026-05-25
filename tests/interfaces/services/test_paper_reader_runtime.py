import json
from datetime import datetime, timezone

from business.boards.paper_radar.public_mapper import map_paper_radar_artifact_to_public_papers
from interfaces.services.paper_artifact_repository import PaperArtifactRepository
from interfaces.services.paper_service import PaperListQuery, PapersApplicationService


def test_default_papers_data_path_uses_newsroom_dir(monkeypatch) -> None:
    monkeypatch.delenv("NEWSROOM_PAPERS_DATA_PATH", raising=False)
    service = PapersApplicationService(artifact_repository=PaperArtifactRepository(artifact_root="missing"))

    assert service.papers_data_path.as_posix().endswith("/.newsroom/papers/arxiv-papers.json")


def test_paper_radar_mapper_filters_non_papers_and_redacts_private_fields() -> None:
    payload = {
        "cards": [
            {
                "id": "paper-card",
                "title": "A Real Paper",
                "summary": "A real abstract.",
                "source_type": "arxiv",
                "url": "https://arxiv.org/abs/2605.00001",
                "raw_payload": {"token": "secret"},
                "evidence_refs": [{"source_id": "arxiv", "url": "https://arxiv.org/abs/2605.00001", "api_key": "secret"}],
            },
            {
                "id": "news-card",
                "title": "OpenAI News",
                "summary": "A blog post.",
                "source_type": "official_blog",
                "url": "https://openai.com/index/example",
            },
        ]
    }

    result = map_paper_radar_artifact_to_public_papers(payload)

    assert len(result["papers"]) == 1
    paper = result["papers"][0]
    assert paper["title"] == "A Real Paper"
    assert paper["arxivUrl"] == "https://arxiv.org/abs/2605.00001"
    serialized = json.dumps(paper)
    assert "raw_payload" not in serialized
    assert "api_key" not in serialized
    assert "secret" not in serialized


def test_paper_service_prefers_latest_artifact_and_preserves_refs(tmp_path) -> None:
    run_dir = tmp_path / "runs" / "paper-run"
    run_dir.mkdir(parents=True)
    (run_dir / "manifest.json").write_text(
        json.dumps({"business_productization": {"board_type": "paper_radar"}, "artifacts": {"board_output": "board_output.json"}}),
        encoding="utf-8",
    )
    (run_dir / "board_output.json").write_text(
        json.dumps(
            {
                "cards": [
                    {
                        "id": "artifact-paper",
                        "title": "Artifact Paper",
                        "summary": "Paper abstract.",
                        "source_type": "arxiv",
                        "url": "https://arxiv.org/abs/2605.00002",
                        "published_at": "2026-05-24T00:00:00Z",
                        "evidence_refs": [{"source_id": "arxiv", "url": "https://arxiv.org/abs/2605.00002"}],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    service = PapersApplicationService(
        artifact_repository=PaperArtifactRepository(artifact_root=tmp_path / "runs"),
        clock=lambda: datetime(2026, 5, 25, tzinfo=timezone.utc),
    )

    result = service.list_papers(PaperListQuery())

    assert result.source == "paper_radar"
    assert result.papers[0].id == "artifact-paper"
    assert result.papers[0].evidenceRefs[0]["sourceId"] == "arxiv"


def test_reader_payload_returns_sections_and_quality(tmp_path) -> None:
    cache_path = tmp_path / "papers.json"
    cache_path.write_text(
        json.dumps(
            {
                "papers": [
                    {
                        "id": "reader-paper",
                        "slug": "reader-paper",
                        "title": "Reader Paper",
                        "abstractSnippet": "Reader abstract.",
                        "authors": ["A"],
                        "publishedAt": "2026-05-24T00:00:00Z",
                        "paperUrl": "https://arxiv.org/abs/2605.00003",
                        "pdfUrl": "https://arxiv.org/pdf/2605.00003.pdf",
                        "isPublished": True,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    service = PapersApplicationService(papers_data_path=cache_path)

    reader = service.get_reader_payload("reader-paper", locale="en").to_dict()

    assert reader["paper"]["id"] == "reader-paper"
    assert reader["sections"][0]["sectionType"] == "abstract"
    assert reader["quality"]["pdfAvailable"] is True
