from fastapi.testclient import TestClient

from interfaces.api import create_app
from interfaces.services.auth_service import AuthApplicationService
from interfaces.services.paper_reader_interaction_service import PaperReaderInteractionApplicationService


def test_reader_interaction_api_requires_auth_isolates_users_and_returns_materials(tmp_path) -> None:
    auth_service = AuthApplicationService(
        user_store_path=tmp_path / "users.json",
        session_store_path=tmp_path / "sessions.json",
    )
    interaction_service = PaperReaderInteractionApplicationService(store_path=tmp_path / "reader-interactions.json")
    worker_service = _FailingWorkerService()
    first_session = auth_service.bootstrap(username="admin", password="correct horse")
    auth_service._create_user(username="reader2", password="correct horse", role="admin")
    second_session = auth_service.login(username="reader2", password="correct horse")
    assert first_session.sessionToken is not None
    assert second_session.sessionToken is not None

    client = TestClient(
        create_app(
            auth_service_factory=lambda: auth_service,
            paper_reader_interaction_service_factory=lambda: interaction_service,
            worker_service_factory=lambda: worker_service,
            audit_emitter_factory=None,
        )
    )

    unauthenticated = client.post(
        "/api/v1/papers/paper-1/reader/events",
        json={"type": "reader_settings_changed", "payload": {"theme": "warm"}},
    )
    assert unauthenticated.status_code == 401
    assert unauthenticated.json()["error"]["code"] == "auth_session_required"

    created = client.post(
        "/api/v1/papers/paper-1/reader/selections",
        json={
            "target": {"targetType": "text_selection", "sectionId": "method", "paragraphId": "p7"},
            "selectedText": "The verifier checks claims.",
            "surroundingText": "The verifier checks claims against evidence.",
            "payload": {"sectionTitle": "Method"},
        },
        headers={"x-newsroom-session": first_session.sessionToken},
    )
    assert created.status_code == 200
    created_payload = created.json()["data"]
    selection_id = created_payload["selection"]["selectionId"]
    assert created_payload["event"]["type"] == "selection_created"
    assert created_payload["materials"]["stats"]["materialCount"] == 0
    assert created_payload["feedbackIngest"]["queued"] is False

    patched = client.patch(
        f"/api/v1/papers/paper-1/reader/selections/{selection_id}",
        json={"noteText": "Verifier means evidence checker."},
        headers={"x-newsroom-session": first_session.sessionToken},
    )
    assert patched.status_code == 200
    patched_payload = patched.json()["data"]
    assert patched_payload["selection"]["status"] == "has_note"
    assert patched_payload["materials"]["stats"]["materialCount"] == 1
    assert worker_service.calls == [
        {"paper_id": "paper-1", "user_id": first_session.user.userId},
        {"paper_id": "paper-1", "user_id": first_session.user.userId},
    ]

    first_materials = client.get(
        "/api/v1/papers/paper-1/reader/materials",
        headers={"x-newsroom-session": first_session.sessionToken},
    )
    assert first_materials.status_code == 200
    assert first_materials.json()["data"]["materials"]["stats"]["noteCount"] == 1

    second_materials = client.get(
        "/api/v1/papers/paper-1/reader/materials",
        headers={"x-newsroom-session": second_session.sessionToken},
    )
    assert second_materials.status_code == 200
    assert second_materials.json()["data"]["materials"]["selections"] == []

    cross_user_patch = client.patch(
        f"/api/v1/papers/paper-1/reader/selections/{selection_id}",
        json={"confused": True},
        headers={"x-newsroom-session": second_session.sessionToken},
    )
    assert cross_user_patch.status_code == 404
    assert cross_user_patch.json()["error"]["code"] == "paper_reader_selection_not_found"

    deleted = client.delete(
        "/api/v1/papers/paper-1/reader/materials",
        headers={"x-newsroom-session": first_session.sessionToken},
    )
    assert deleted.status_code == 200
    assert deleted.json()["data"]["deleted"]["eventsDeleted"] == 2
    assert deleted.json()["data"]["deleted"]["selectionsDeleted"] == 1


def test_reader_event_api_supports_figure_and_table_targets(tmp_path) -> None:
    auth_service = AuthApplicationService(
        user_store_path=tmp_path / "users.json",
        session_store_path=tmp_path / "sessions.json",
    )
    interaction_service = PaperReaderInteractionApplicationService(store_path=tmp_path / "reader-interactions.json")
    worker_service = _EnqueueingWorkerService()
    session = auth_service.bootstrap(username="admin", password="correct horse")
    assert session.sessionToken is not None
    client = TestClient(
        create_app(
            auth_service_factory=lambda: auth_service,
            paper_reader_interaction_service_factory=lambda: interaction_service,
            worker_service_factory=lambda: worker_service,
            audit_emitter_factory=None,
        )
    )

    figure = client.post(
        "/api/v1/papers/paper-1/reader/events",
        json={
            "type": "figure_explanation_requested",
            "target": {"targetType": "figure", "blockId": "fig-1", "pageNumber": 3},
            "payload": {"question": "What does the verifier module do?"},
        },
        headers={"x-newsroom-session": session.sessionToken},
    )
    table = client.post(
        "/api/v1/papers/paper-1/reader/events",
        json={
            "type": "table_explanation_requested",
            "target": {"targetType": "table", "blockId": "table-1", "pageNumber": 6},
            "payload": {"question": "Which row is the ablation?"},
        },
        headers={"x-newsroom-session": session.sessionToken},
    )

    assert figure.status_code == 200
    assert table.status_code == 200
    materials = client.get(
        "/api/v1/papers/paper-1/reader/materials",
        headers={"x-newsroom-session": session.sessionToken},
    ).json()["data"]["materials"]
    assert [event["target"]["targetType"] for event in materials["events"]] == ["figure", "table"]
    assert len(worker_service.calls) == 2


class _FailingWorkerService:
    def __init__(self) -> None:
        self.calls = []

    def enqueue_paper_reader_feedback(self, *, paper_id: str, user_id: str | None = None, **kwargs):
        self.calls.append({"paper_id": paper_id, "user_id": user_id})
        raise RuntimeError("queue unavailable")


class _EnqueueingWorkerService:
    def __init__(self) -> None:
        self.calls = []

    def enqueue_paper_reader_feedback(self, *, paper_id: str, user_id: str | None = None, **kwargs):
        self.calls.append({"paper_id": paper_id, "user_id": user_id})
        return _Enqueued()


class _Enqueued:
    def to_dict(self):
        return {
            "message_id": "message-1",
            "task_id": "task-1",
            "task_type": "paper_reader.feedback_ingest",
            "queue_name": "news:queue:memory",
            "status": "queued",
        }
