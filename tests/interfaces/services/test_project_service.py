from __future__ import annotations

import json

from business.projects.bridge import ProjectRadarBridge
from business.projects.repository import ProjectArtifactRepository, ProjectStateRepository
from business.projects.service import ProjectDomainService
from interfaces.services.project_service import ProjectApplicationService


def test_project_application_service_reads_real_project_radar_artifact(tmp_path) -> None:
    runs_root = tmp_path / "runs"
    run_dir = runs_root / "real-data-business-20260529-project_radar"
    run_dir.mkdir(parents=True)
    (run_dir / "board_output.json").write_text(json.dumps(_board_output_payload()), encoding="utf-8")

    service = ProjectApplicationService(runs_root=runs_root, state_path=tmp_path / "state.json")
    result = service.list_hot(_query(limit=10))

    assert result["meta"]["source"] == "artifact"
    assert result["meta"]["source_run_id"] == "real-data-business-20260529-project_radar"
    assert result["items"][0]["name"] == "example-agent"
    assert result["items"][0]["github_url"] == "https://github.com/acme/example-agent"
    assert result["items"][0]["hot_score"] is not None
    assert "raw_payload" not in json.dumps(result)
    assert "secret-token" not in json.dumps(result)


def test_project_application_service_reads_uuid_run_marked_by_manifest(tmp_path) -> None:
    runs_root = tmp_path / "runs"
    run_dir = runs_root / "8dfa86ad652148b7b0cc24e6c1e47edb"
    run_dir.mkdir(parents=True)
    (run_dir / "manifest.json").write_text(
        json.dumps(
            {
                "run_id": run_dir.name,
                "business_productization": {"board_type": "project_radar"},
                "artifacts": {"board_output": "board_output.json"},
            }
        ),
        encoding="utf-8",
    )
    (run_dir / "board_output.json").write_text(json.dumps(_board_output_payload()), encoding="utf-8")

    service = ProjectApplicationService(runs_root=runs_root, state_path=tmp_path / "state.json")
    result = service.list_hot(_query(limit=10))

    assert result["meta"]["source"] == "artifact"
    assert result["meta"]["source_run_id"] == run_dir.name
    assert result["items"][0]["name"] == "example-agent"


def test_project_application_service_returns_empty_without_fake_projects(tmp_path) -> None:
    service = ProjectApplicationService(runs_root=tmp_path / "missing-runs", state_path=tmp_path / "state.json")

    result = service.list_projects(_query(limit=10))

    assert result["items"] == []
    assert result["meta"]["source"] == "none"
    assert result["meta"]["data_state"] == "empty"
    assert "No real Project Radar artifacts" in " ".join(result["meta"]["notices"])


def test_project_application_service_tools_cases_lab_watchlist_and_interactions(tmp_path) -> None:
    domain = ProjectDomainService(
        artifact_repository=_memory_artifact_repository(_board_output_payload()),
        state_repository=ProjectStateRepository(tmp_path / "state.json"),
    )
    service = ProjectApplicationService(domain_service=domain)

    tools = service.search_tools(_tool_query(limit=5))
    cases = service.search_cases(_case_query(limit=5))
    watch = service.add_watchlist(
        _watch_request(
            project_id="card_example_agent",
            watch_reason="Track agent workflow releases.",
            watch_topics=["release", "workflow"],
            priority="high",
        )
    )
    watch_updated = service.add_watchlist(
        _watch_request(
            project_id="card_example_agent",
            watch_reason="Track docs and releases.",
            watch_topics=["docs_change", "release"],
            priority="medium",
        )
    )
    session = service.start_lab_session(
        _lab_request(
            user_problem="Need a traceable agent workflow module.",
            business_domain="product_engineering",
            module_type="workflow",
            selected_case_ids=[cases["cases"][0]["id"]],
        )
    )
    answered = service.answer_lab_question(
        session["id"],
        _lab_answer(session["questions"][0]["id"], "Quality score and release cadence."),
    )
    solution = service.generate_lab_solution(session["id"])
    event = service.record_interaction(
        _interaction(target_id="card_example_agent", event_type="view", target_type="project")
    )
    second_event = service.record_interaction(
        _interaction(target_id="card_example_agent", event_type="view", target_type="project")
    )
    watchlist = service.list_watchlist(user_id="anonymous")

    assert tools["tools"][0]["project"]["id"] == "card_example_agent"
    assert cases["cases"][0]["project_id"] == "card_example_agent"
    assert watch["priority"] == "high"
    assert watch_updated["priority"] == "medium"
    assert watchlist["items"][0]["watch_reason"] == "Track docs and releases."
    assert session["selected_case_ids"] == [cases["cases"][0]["id"]]
    assert answered["questions"][0]["answered_value"] == "Quality score and release cadence."
    assert solution["solution"]["solution_json"]["project_ids"] == ["card_example_agent"]
    assert event["target_id"] == "card_example_agent"
    assert event["id"] != second_event["id"]
    assert (tmp_path / "state.json").exists()


class _memory_artifact_repository(ProjectArtifactRepository):
    def __init__(self, payload):
        super().__init__(runs_root="unused", bridge=ProjectRadarBridge())
        self.payload = payload

    def load_dataset(self):
        return self.bridge.map_payload(self.payload, source="artifact", source_run_id="memory-project-radar")


def _board_output_payload() -> dict:
    return {
        "board_type": "project_radar",
        "generated_at": "2026-05-29T08:00:00Z",
        "cards": [
            {
                "card_id": "card_example_agent",
                "title": "example-agent",
                "summary": "Agent workflow CLI with API support. https://github.com/acme/example-agent",
                "repo_full_name": "acme/example-agent",
                "github_url": "https://github.com/acme/example-agent",
                "tags": ["agent", "workflow", "cli", "api"],
                "stars": 2400,
                "forks": 180,
                "star_growth_7d": 140,
                "generated_at": "2026-05-29T08:00:00Z",
                "ranking_reason": "Real Project Radar ranking reason.",
                "ranking_features": {
                    "repo_health": 0.8,
                    "activity": 0.9,
                    "implementation_evidence": 0.85,
                    "community_adoption": 0.4,
                    "technology_mapping": 0.7,
                },
                "confidence": {"value": 0.95},
                "evidence_refs": [
                    {
                        "source_name": "GitHub",
                        "source_type": "github",
                        "url": "https://github.com/acme/example-agent",
                        "raw_payload": {"token": "secret-token"},
                    }
                ],
            }
        ],
        "detail_pages": [
            {
                "title": "example-agent",
                "primary_object_ref": {"label": "example-agent"},
                "sections": [{"title": "Summary", "content": "Detail page for example-agent."}],
            }
        ],
    }


def _query(**kwargs):
    from business.projects.dto import ProjectListQuery

    return ProjectListQuery(**kwargs)


def _tool_query(**kwargs):
    from business.projects.dto import ToolSearchQuery

    return ToolSearchQuery(**kwargs)


def _case_query(**kwargs):
    from business.projects.dto import CaseSearchQuery

    return CaseSearchQuery(**kwargs)


def _watch_request(**kwargs):
    from business.projects.dto import WatchlistCreateRequest

    return WatchlistCreateRequest(**kwargs)


def _lab_request(**kwargs):
    from business.projects.dto import LabSessionRequest

    return LabSessionRequest(**kwargs)


def _lab_answer(question_id, answer):
    from business.projects.dto import LabAnswerRequest

    return LabAnswerRequest(question_id=question_id, answer=answer)


def _interaction(**kwargs):
    from business.projects.dto import InteractionRequest

    return InteractionRequest(**kwargs)
