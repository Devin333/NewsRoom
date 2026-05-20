import json

from interfaces.services.entity_service import EntityTrackingApplicationService
from infrastructure.storage.entities import LocalJsonTrackedEntityStore
from business.boards.cross_board.workflows.daily_intelligence.profiles import LEGACY_DAILY_WORKFLOW_ID


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
        workflow_id=LEGACY_DAILY_WORKFLOW_ID,
    )
    payload = result.to_dict()

    assert payload["match_count"] == 1
    assert payload["matches"][0]["report_id"] == "run-1:final"
    assert payload["matches"][0]["matched_aliases"] == ["OpenAI", "ChatGPT"]


def test_entity_service_matches_reports_by_daily_workflow_family(tmp_path) -> None:
    store_path = tmp_path / "entities.json"
    artifact_root = tmp_path / "runs"
    service = EntityTrackingApplicationService(store_path=store_path)
    entity = service.create_entity(name="OpenAI", aliases=["ChatGPT"])
    _write_report_run(artifact_root, "run-legacy", "Daily Intelligence: OpenAI")
    _write_report_run(
        artifact_root,
        "run-agentic",
        "Daily Intelligence: ChatGPT",
        workflow_id="daily-intelligence-agentic",
    )

    result = service.match_reports(
        entity.entity_id,
        artifact_root=artifact_root,
        workflow_family="daily",
    )
    payload = result.to_dict()

    assert payload["workflow_family"] == "daily"
    assert payload["match_count"] == 2
    assert {match["workflow_id"] for match in payload["matches"]} == {
        LEGACY_DAILY_WORKFLOW_ID,
        "daily-intelligence-agentic",
    }


def _write_report_run(
    root,
    run_id: str,
    title: str,
    *,
    workflow_id: str = LEGACY_DAILY_WORKFLOW_ID,
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
                "workflow_id": workflow_id,
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
