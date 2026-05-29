from __future__ import annotations

from business.projects.dto import InteractionRequest, WatchlistCreateRequest
from business.projects.models import ProjectDataset
from business.projects.repository import ProjectStateRepository
from business.projects.service import ProjectDomainService
from tests.business.projects.helpers import project_dataset_payload


class _StaticArtifactRepository:
    def load_dataset(self):
        return ProjectDataset.model_validate(project_dataset_payload())


def test_watchlist_and_interactions_persist_to_injected_state_path(tmp_path) -> None:
    state_path = tmp_path / "state.json"
    service = ProjectDomainService(
        artifact_repository=_StaticArtifactRepository(),
        state_repository=ProjectStateRepository(state_path),
    )

    first = service.add_watchlist(
        WatchlistCreateRequest(
            project_id="project-langfuse",
            watch_reason="Track observability releases.",
            watch_topics=["release"],
            priority="high",
        )
    )
    second = service.add_watchlist(
        WatchlistCreateRequest(
            project_id="project-langfuse",
            watch_reason="Track docs changes.",
            watch_topics=["docs_change"],
            priority="medium",
        )
    )
    event = service.record_interaction(
        InteractionRequest(event_type="view", target_type="project", target_id="project-langfuse")
    )
    watchlist = service.list_watchlist(user_id="anonymous")

    assert first.id == second.id
    assert second.watch_reason == "Track docs changes."
    assert watchlist.items[0].watch_topics == ["docs_change"]
    assert event.id
    assert state_path.exists()
    assert ProjectStateRepository(state_path).load().interaction_events[0].target_id == "project-langfuse"


def test_watchlist_rejects_unknown_project(tmp_path) -> None:
    service = ProjectDomainService(
        artifact_repository=_StaticArtifactRepository(),
        state_repository=ProjectStateRepository(tmp_path / "state.json"),
    )

    try:
        service.add_watchlist(WatchlistCreateRequest(project_id="missing", watch_reason="Track"))
    except ValueError as exc:
        assert "project not found" in str(exc)
    else:
        raise AssertionError("unknown project should be rejected")
