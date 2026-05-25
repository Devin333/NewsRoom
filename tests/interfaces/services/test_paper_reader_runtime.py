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
    assert reader["relatedPapers"] == []
    assert reader["relatedProjects"] == []
    assert reader["relatedNews"] == []
    assert reader["quality"]["pdfAvailable"] is True


def test_reader_cache_miss_writes_public_cache(tmp_path) -> None:
    cache_path = tmp_path / "papers.json"
    reader_cache_dir = tmp_path / "reader-cache"
    cache_path.write_text(
        json.dumps(
            {
                "papers": [
                    {
                        "id": "cache-paper",
                        "slug": "cache-paper",
                        "title": "Cache Paper",
                        "abstractSnippet": "Cache abstract.",
                        "authors": ["A"],
                        "publishedAt": "2026-05-24T00:00:00Z",
                        "paperUrl": "https://arxiv.org/abs/2605.10001",
                        "evidenceRefs": [{"sourceId": "arxiv", "raw_payload": {"token": "secret"}}],
                        "isPublished": True,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    service = PapersApplicationService(papers_data_path=cache_path, reader_cache_dir=reader_cache_dir)

    reader = service.get_reader_payload("cache-paper", locale="en").to_dict()

    cache_file = reader_cache_dir / "cache-paper.json"
    assert cache_file.exists()
    assert reader["sections"][0]["sectionType"] == "abstract"
    cache_record = json.loads(cache_file.read_text(encoding="utf-8"))
    assert cache_record["paperId"] == "cache-paper"
    assert cache_record["sourceHash"]
    assert cache_record["payload"]["paper"]["id"] == "cache-paper"
    serialized = json.dumps(cache_record)
    assert "raw_payload" not in serialized
    assert "token" not in serialized
    assert "secret" not in serialized


def test_reader_cache_reuses_valid_cache_and_rebuilds_stale_cache(tmp_path) -> None:
    cache_path = tmp_path / "papers.json"
    reader_cache_dir = tmp_path / "reader-cache"
    cache_path.write_text(
        json.dumps(
            {
                "papers": [
                    {
                        "id": "reuse-paper",
                        "slug": "reuse-paper",
                        "title": "Reuse Paper",
                        "abstractSnippet": "Original cacheable abstract.",
                        "authors": ["A"],
                        "publishedAt": "2026-05-24T00:00:00Z",
                        "paperUrl": "https://arxiv.org/abs/2605.10002",
                        "isPublished": True,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    service = PapersApplicationService(papers_data_path=cache_path, reader_cache_dir=reader_cache_dir)
    service.get_reader_payload("reuse-paper", locale="en")
    cache_file = reader_cache_dir / "reuse-paper.json"
    cache_record = json.loads(cache_file.read_text(encoding="utf-8"))
    cache_record["payload"]["sections"][0]["textExcerpt"] = "Cached public section."
    cache_record["payload"]["raw_payload"] = {"token": "secret"}
    cache_record["payload"]["sections"][0]["authorization"] = "Bearer secret"
    cache_file.write_text(json.dumps(cache_record), encoding="utf-8")

    cached_reader = service.get_reader_payload("reuse-paper", locale="en").to_dict()

    assert cached_reader["sections"][0]["textExcerpt"] == "Cached public section."
    serialized = json.dumps(cached_reader)
    assert "raw_payload" not in serialized
    assert "authorization" not in serialized
    assert "token" not in serialized

    stale_record = json.loads(cache_file.read_text(encoding="utf-8"))
    stale_record["sourceHash"] = "stale"
    stale_record["payload"]["sections"][0]["textExcerpt"] = "Stale cache should not leak."
    cache_file.write_text(json.dumps(stale_record), encoding="utf-8")

    rebuilt_reader = service.get_reader_payload("reuse-paper", locale="en").to_dict()

    assert rebuilt_reader["sections"][0]["textExcerpt"] == "Original cacheable abstract."
    assert json.loads(cache_file.read_text(encoding="utf-8"))["sourceHash"] != "stale"


def test_text_extraction_artifact_adds_sections_and_text_extracted_quality(tmp_path) -> None:
    cache_path = tmp_path / "papers.json"
    reader_cache_dir = tmp_path / "reader-cache"
    text_extraction_dir = tmp_path / "text-extractions"
    cache_path.write_text(
        json.dumps(
            {
                "papers": [
                    {
                        "id": "extract-paper",
                        "slug": "extract-paper",
                        "title": "Extract Paper",
                        "abstractSnippet": "Metadata abstract.",
                        "authors": ["A"],
                        "publishedAt": "2026-05-24T00:00:00Z",
                        "paperUrl": "https://arxiv.org/abs/2605.10003",
                        "isPublished": True,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    service = PapersApplicationService(
        papers_data_path=cache_path,
        reader_cache_dir=reader_cache_dir,
        text_extraction_dir=text_extraction_dir,
    )
    service.get_reader_payload("extract-paper", locale="en")
    base_source_hash = json.loads((reader_cache_dir / "extract-paper.json").read_text(encoding="utf-8"))["baseSourceHash"]
    text_extraction_dir.mkdir()
    (text_extraction_dir / "extract-paper.json").write_text(
        json.dumps(
            {
                "paperId": "extract-paper",
                "sourceHash": base_source_hash,
                "extractedAt": "2026-05-25T00:00:00Z",
                "sections": [
                    {
                        "title": "Method",
                        "level": 2,
                        "pageStart": 3,
                        "pageEnd": 4,
                        "textExcerpt": "Extracted method details from a safe artifact.",
                        "summary": "Extracted method summary.",
                        "sectionType": "method",
                        "raw_payload": {"token": "secret"},
                        "full_text": "private full text",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    reader = service.get_reader_payload("extract-paper", locale="en").to_dict()

    assert reader["quality"]["textExtracted"] is True
    assert reader["sections"][0]["id"].startswith("extract-paper:extracted:method:")
    assert reader["sections"][0]["pageStart"] == 3
    assert reader["sections"][0]["summary"] == "Extracted method summary."
    assert any(section["sectionType"] == "abstract" for section in reader["sections"])
    serialized = json.dumps(reader)
    assert "raw_payload" not in serialized
    assert "full_text" not in serialized
    assert "token" not in serialized
    assert "secret" not in serialized


def test_corrupt_reader_cache_or_extraction_artifact_does_not_break_payload(tmp_path) -> None:
    cache_path = tmp_path / "papers.json"
    reader_cache_dir = tmp_path / "reader-cache"
    text_extraction_dir = tmp_path / "text-extractions"
    cache_path.write_text(
        json.dumps(
            {
                "papers": [
                    {
                        "id": "corrupt-paper",
                        "slug": "corrupt-paper",
                        "title": "Corrupt Paper",
                        "abstractSnippet": "Corrupt fallback abstract.",
                        "authors": ["A"],
                        "publishedAt": "2026-05-24T00:00:00Z",
                        "paperUrl": "https://arxiv.org/abs/2605.10004",
                        "isPublished": True,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    reader_cache_dir.mkdir()
    text_extraction_dir.mkdir()
    (reader_cache_dir / "corrupt-paper.json").write_text("{not-json", encoding="utf-8")
    (text_extraction_dir / "corrupt-paper.json").write_text("{not-json", encoding="utf-8")
    service = PapersApplicationService(
        papers_data_path=cache_path,
        reader_cache_dir=reader_cache_dir,
        text_extraction_dir=text_extraction_dir,
    )

    reader = service.get_reader_payload("corrupt-paper", locale="en").to_dict()

    assert reader["sections"][0]["textExcerpt"] == "Corrupt fallback abstract."
    assert reader["quality"]["textExtracted"] is False


def test_reader_payload_builds_public_derived_sections_and_ranks_answers(tmp_path) -> None:
    cache_path = tmp_path / "papers.json"
    summary_path = tmp_path / "summaries.json"
    cache_path.write_text(
        json.dumps(
            {
                "papers": [
                    {
                        "id": "section-paper",
                        "slug": "section-paper",
                        "title": "Section Paper",
                        "abstractSnippet": "The paper studies grounded evaluation for reader agents.",
                        "authors": ["A"],
                        "publishedAt": "2026-05-24T00:00:00Z",
                        "paperUrl": "https://arxiv.org/abs/2605.00005",
                        "projectUrl": "https://example.com/section-paper",
                        "tags": ["reader", "evaluation"],
                        "taskRefs": [{"id": "task-qa", "slug": "qa", "name": "Question Answering"}],
                        "methodRefs": [{"id": "method-rag", "slug": "rag", "name": "Retrieval Augmented Generation"}],
                        "repoUrl": "https://github.com/owner/section-paper",
                        "githubStars": 42,
                        "benchmarks": [
                            {
                                "id": "bench-mmlu",
                                "name": "MMLU",
                                "metric": "accuracy",
                                "value": "91.2",
                                "taskSlug": "qa",
                                "url": "https://papers.example/bench",
                            }
                        ],
                        "evidenceRefs": [
                            {
                                "evidenceId": "ev-section",
                                "title": "arXiv abstract",
                                "sourceType": "arxiv",
                                "summary": "Public evidence summary.",
                                "url": "https://arxiv.org/abs/2605.00005",
                                "raw_payload": {"token": "secret"},
                                "authorization": "Bearer secret",
                            },
                            {
                                "evidenceId": "ev-blog",
                                "title": "Release note",
                                "sourceType": "official_blog",
                                "summary": "Public release context.",
                                "url": "https://example.com/news/section-paper",
                                "raw_content": "secret",
                            }
                        ],
                        "sourceRefs": [
                            {
                                "sourceId": "arxiv",
                                "sourceName": "arXiv",
                                "full_text": "private text",
                                "url": "https://arxiv.org/abs/2605.00005",
                            }
                        ],
                        "isPublished": True,
                    },
                    {
                        "id": "related-paper",
                        "slug": "related-paper",
                        "title": "Related Reader Paper",
                        "abstractSnippet": "A second paper studies grounded reader evaluation.",
                        "authors": ["B"],
                        "publishedAt": "2026-05-23T00:00:00Z",
                        "paperUrl": "https://arxiv.org/abs/2605.00006",
                        "tags": ["reader", "evaluation"],
                        "taskRefs": [{"id": "task-qa", "slug": "qa", "name": "Question Answering"}],
                        "methodRefs": [{"id": "method-rag", "slug": "rag", "name": "Retrieval Augmented Generation"}],
                        "sourceRefs": [{"sourceId": "arxiv", "sourceName": "arXiv"}],
                        "isPublished": True,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    class FakeClient:
        def complete(self, request):
            class Response:
                content = json.dumps(
                    {
                        "summary": "The system retrieves public sections before answering.",
                        "keyInsights": ["Grounded answers cite the most relevant paper section."],
                        "limitations": ["The approach does not parse full PDF text yet."],
                    }
                )

            return Response()

    service = PapersApplicationService(
        papers_data_path=cache_path,
        summary_cache_path=summary_path,
        llm_client_factory=lambda route: FakeClient(),
        clock=lambda: datetime(2026, 5, 25, tzinfo=timezone.utc),
    )
    service.get_or_generate_summary("section-paper", locale="en")

    reader = service.get_reader_payload("section-paper", locale="en").to_dict()
    section_by_type = {section["sectionType"]: section for section in reader["sections"]}

    assert [section["id"] for section in reader["sections"]] == [
        "section-paper:abstract",
        "section-paper:summary",
        "section-paper:contribution",
        "section-paper:limitation",
        "section-paper:method",
        "section-paper:experiment",
        "section-paper:benchmark",
        "section-paper:implementation",
        "section-paper:evidence",
    ]
    assert "Retrieval Augmented Generation" in section_by_type["method"]["textExcerpt"]
    assert "MMLU" in section_by_type["benchmark"]["textExcerpt"]
    assert "github.com/owner/section-paper" in section_by_type["implementation"]["textExcerpt"]
    assert reader["relatedPapers"][0]["id"] == "related-paper"
    assert reader["relatedPapers"][0]["slug"] == "related-paper"
    assert "Shared methods" in reader["relatedPapers"][0]["relationReason"]
    assert all(item["id"] != "section-paper" for item in reader["relatedPapers"])
    assert reader["relatedProjects"][0]["url"] == "https://github.com/owner/section-paper"
    assert any(item["url"] == "https://example.com/section-paper" for item in reader["relatedProjects"])
    assert reader["relatedNews"][0]["url"] == "https://example.com/news/section-paper"
    assert reader["relatedNews"][0]["sourceType"] == "official_blog"
    assert reader["quality"]["textExtracted"] is False
    assert reader["quality"]["implementationVerified"] is True
    assert reader["quality"]["benchmarkVerified"] is True
    assert reader["quality"]["evidenceCoverage"] == 1.0

    serialized = json.dumps(reader)
    assert "raw_payload" not in serialized
    assert "authorization" not in serialized
    assert "full_text" not in serialized
    assert "token" not in serialized
    assert "secret" not in serialized

    answer = service.ask_paper("section-paper", question="Which benchmark result is reported?", locale="en").to_dict()

    assert answer["citations"][0]["sectionId"] == "section-paper:benchmark"
    assert "MMLU" in answer["answer"]

    sections = service.get_paper_sections("section-paper", locale="en")
    related_papers = service.get_related_papers("section-paper")
    graph = service.get_paper_graph("section-paper")
    tasks = service.list_tasks()
    methods = service.list_methods()

    assert sections[0]["id"] == "section-paper:abstract"
    assert related_papers[0]["id"] == "related-paper"
    assert any(node["type"] == "project" for node in graph["nodes"])
    assert any(edge["target"].startswith("news:") for edge in graph["edges"])
    assert tasks[0]["slug"] == "qa"
    assert tasks[0]["paperCount"] == 2
    assert tasks[0]["methodCount"] == 1
    assert methods[0]["slug"] == "rag"
    assert methods[0]["paperCount"] == 2
    assert methods[0]["taskCount"] == 1


def test_reader_agent_answers_with_citations_cache_and_redaction(tmp_path) -> None:
    cache_path = tmp_path / "papers.json"
    cache_path.write_text(
        json.dumps(
            {
                "papers": [
                    {
                        "id": "ask-paper",
                        "slug": "ask-paper",
                        "title": "Harness Paper",
                        "abstractSnippet": "The paper introduces a trial harness for autonomous research agents.",
                        "authors": ["A"],
                        "publishedAt": "2026-05-24T00:00:00Z",
                        "paperUrl": "https://arxiv.org/abs/2605.00004",
                        "evidenceRefs": [
                            {
                                "evidenceId": "ev-1",
                                "sourceId": "arxiv",
                                "summary": "Harness evidence.",
                                "raw_payload": {"token": "secret"},
                            }
                        ],
                        "isPublished": True,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    service = PapersApplicationService(papers_data_path=cache_path)

    first = service.ask_paper("ask-paper", question="What harness does it introduce?", locale="en").to_dict()
    second = service.ask_paper("ask-paper", question="What harness does it introduce?", locale="en").to_dict()

    assert "trial harness" in first["answer"]
    assert first["citations"][0]["sourceType"] == "section"
    assert any(citation["sourceType"] == "evidence" for citation in first["citations"])
    assert first["cached"] is False
    assert second["cached"] is True
    serialized = json.dumps(first)
    assert "raw_payload" not in serialized
    assert "token" not in serialized
    assert "secret" not in serialized
