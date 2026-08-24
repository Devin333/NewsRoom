import json

from interfaces.services.entity_service import EntityTrackingApplicationService
from infrastructure.storage.entities import LocalJsonTrackedEntityStore


RESEARCH_GRAPH_ID = "research.paper-analysis"


def test_entity_service_creates_stable_id_and_lists(tmp_path) -> None:
    service = EntityTrackingApplicationService(
        store=LocalJsonTrackedEntityStore(tmp_path / "entities.json")
    )

    created = service.create_entity(name="OpenAI", kind="company", aliases=["ChatGPT"])
    listed = service.list_entities(kind="company")

    assert created.entity_id.startswith("company:openai:")
    assert listed.to_dict()["entity_count"] == 1
    assert listed.to_dict()["entities"][0]["aliases"] == ["ChatGPT"]


def test_entity_service_matches_real_report_artifacts(tmp_path) -> None:
    store_path = tmp_path / "entities.json"
    artifact_root = tmp_path / "runs"
    service = EntityTrackingApplicationService(store_path=store_path)
    entity = service.create_entity(name="OpenAI", aliases=["ChatGPT"])
    _write_report_run(artifact_root, "run-1", "Daily Intelligence: OpenAI")

    result = service.match_reports(
        entity.entity_id,
        artifact_root=artifact_root,
        graph_id=RESEARCH_GRAPH_ID,
    )
    payload = result.to_dict()

    assert payload["match_count"] == 1
    assert payload["matches"][0]["report_id"] == "run-1:final"
    assert payload["matches"][0]["matched_aliases"] == ["OpenAI", "ChatGPT"]


def test_entity_service_filters_reports_by_graph_ids(tmp_path) -> None:
    store_path = tmp_path / "entities.json"
    artifact_root = tmp_path / "runs"
    service = EntityTrackingApplicationService(store_path=store_path)
    entity = service.create_entity(name="OpenAI", aliases=["ChatGPT"])
    _write_report_run(artifact_root, "run-research", "Research Analysis: OpenAI")
    _write_report_run(
        artifact_root,
        "run-other",
        "Other Analysis: ChatGPT",
        graph_id="other.graph",
    )

    result = service.match_reports(
        entity.entity_id,
        artifact_root=artifact_root,
        graph_ids=(RESEARCH_GRAPH_ID, "other.graph"),
    )
    payload = result.to_dict()

    assert payload["graph_ids"] == [RESEARCH_GRAPH_ID, "other.graph"]
    assert payload["match_count"] == 2
    assert {match["graph_id"] for match in payload["matches"]} == {
        RESEARCH_GRAPH_ID,
        "other.graph",
    }


def _write_report_run(
    root,
    run_id: str,
    title: str,
    *,
    graph_id: str = RESEARCH_GRAPH_ID,
) -> None:
    run_dir = root / run_id
    run_dir.mkdir(parents=True)
    (run_dir / "report.json").write_text(
        json.dumps(
            {
                "title": title,
                "sections": [
                    {
                        "title": "Summary",
                        "content": "OpenAI and ChatGPT appeared in the daily report.",
                        "sources": ["https://example.com/openai"],
                    }
                ],
                "source_urls": ["https://example.com/openai"],
            }
        ),
        encoding="utf-8",
    )
    (run_dir / "report.md").write_text(f"# {title}\n\nOpenAI and ChatGPT.\n", encoding="utf-8")
    (run_dir / "manifest.json").write_text(
        json.dumps(
            {
                "run_id": run_id,
                "graph_id": graph_id,
                "graph_version": "2",
                "profile": "live-offline",
                "status": "succeeded",
                "finished_at": "2026-05-11T00:00:00Z",
                "quality_score": 0.9,
                "artifacts": {
                    "report_json": "report.json",
                    "report_markdown": "report.md",
                },
            }
        ),
        encoding="utf-8",
    )
