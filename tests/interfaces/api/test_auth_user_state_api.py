import json

from fastapi.testclient import TestClient

from interfaces.api import create_app
from interfaces.services.auth_service import AuthApplicationService
from interfaces.services.paper_reader_notes_service import PaperReaderNotesApplicationService
from interfaces.services.paper_user_state_service import PaperUserStateApplicationService


def test_auth_bootstrap_login_logout_session_and_redaction(tmp_path) -> None:
    auth_service = AuthApplicationService(
        user_store_path=tmp_path / "users.json",
        session_store_path=tmp_path / "sessions.json",
    )
    client = TestClient(
        create_app(
            auth_service_factory=lambda: auth_service,
            audit_emitter_factory=None,
        )
    )

    bootstrap = client.post(
        "/api/v1/auth/bootstrap",
        json={"username": "admin", "password": "correct horse"},
    )
    payload = bootstrap.json()
    session = payload["data"]["session"]
    token = session["sessionToken"]

    assert bootstrap.status_code == 200
    assert session["user"]["username"] == "admin"
    assert session["user"]["role"] == "admin"
    serialized = json.dumps(payload)
    assert "passwordHash" not in serialized
    assert "passwordSalt" not in serialized
    assert "tokenDigest" not in serialized

    stored = json.loads((tmp_path / "users.json").read_text(encoding="utf-8"))
    assert stored["users"][0]["passwordHash"] != "correct horse"
    assert "password" not in stored["users"][0]

    second_bootstrap = client.post(
        "/api/v1/auth/bootstrap",
        json={"username": "second", "password": "correct horse"},
    )
    assert second_bootstrap.status_code == 409
    assert second_bootstrap.json()["error"]["code"] == "auth_already_initialized"

    bad_login = client.post(
        "/api/v1/auth/login",
        json={"username": "admin", "password": "wrong horse"},
    )
    assert bad_login.status_code == 401
    assert bad_login.json()["error"]["code"] == "auth_invalid_credentials"

    good_login = client.post(
        "/api/v1/auth/login",
        json={"username": "admin", "password": "correct horse"},
    )
    assert good_login.status_code == 200
    login_token = good_login.json()["data"]["session"]["sessionToken"]

    current = client.get("/api/v1/auth/session", headers={"x-newsroom-session": login_token})
    assert current.status_code == 200
    assert current.json()["data"]["session"]["user"]["username"] == "admin"

    logout = client.post("/api/v1/auth/logout", json={}, headers={"x-newsroom-session": login_token})
    assert logout.status_code == 200
    assert logout.json()["data"]["revoked"] is True

    revoked = client.get("/api/v1/auth/session", headers={"x-newsroom-session": login_token})
    assert revoked.status_code == 200
    assert revoked.json()["data"]["session"] is None
    assert revoked.json()["data"]["initialized"] is True
    assert token


def test_paper_user_state_requires_auth_validates_and_isolates_users(tmp_path) -> None:
    auth_service = AuthApplicationService(
        user_store_path=tmp_path / "users.json",
        session_store_path=tmp_path / "sessions.json",
    )
    state_service = PaperUserStateApplicationService(store_path=tmp_path / "user-state.json")
    first_session = auth_service.bootstrap(username="admin", password="correct horse")
    auth_service._create_user(username="reader2", password="correct horse", role="admin")
    second_session = auth_service.login(username="reader2", password="correct horse")
    assert first_session.sessionToken is not None
    assert second_session.sessionToken is not None

    client = TestClient(
        create_app(
            auth_service_factory=lambda: auth_service,
            paper_user_state_service_factory=lambda: state_service,
            audit_emitter_factory=None,
        )
    )

    unauthenticated = client.get("/api/v1/papers/paper-1/state")
    assert unauthenticated.status_code == 401
    assert unauthenticated.json()["error"]["code"] == "auth_session_required"

    default_state = client.get(
        "/api/v1/papers/paper-1/state",
        headers={"x-newsroom-session": first_session.sessionToken},
    )
    assert default_state.status_code == 200
    assert default_state.json()["data"]["state"]["readingStatus"] == "unread"
    assert default_state.json()["data"]["state"]["favorite"] is False

    patched = client.patch(
        "/api/v1/papers/paper-1/state",
        json={
            "favorite": True,
            "subscribed": True,
            "readingStatus": "reading",
            "currentPage": 3,
            "progressPercent": 50,
        },
        headers={"x-newsroom-session": first_session.sessionToken},
    )
    state = patched.json()["data"]["state"]
    assert patched.status_code == 200
    assert state["favorite"] is True
    assert state["subscribed"] is True
    assert state["readingStatus"] == "reading"
    assert state["currentPage"] == 3
    assert state["progressPercent"] == 50

    second_user_state = client.get(
        "/api/v1/papers/paper-1/state",
        headers={"x-newsroom-session": second_session.sessionToken},
    )
    assert second_user_state.status_code == 200
    assert second_user_state.json()["data"]["state"]["favorite"] is False

    batch = client.get(
        "/api/v1/papers/me/state?paperIds=paper-1,paper-2",
        headers={"x-newsroom-session": first_session.sessionToken},
    )
    assert batch.status_code == 200
    assert [item["paperId"] for item in batch.json()["data"]["states"]] == ["paper-1", "paper-2"]

    invalid = client.patch(
        "/api/v1/papers/paper-1/state",
        json={"progressPercent": 101},
        headers={"x-newsroom-session": first_session.sessionToken},
    )
    assert invalid.status_code in {400, 422}


def test_paper_reader_notes_crud_requires_auth_validates_isolates_and_redacts(tmp_path) -> None:
    auth_service = AuthApplicationService(
        user_store_path=tmp_path / "users.json",
        session_store_path=tmp_path / "sessions.json",
    )
    notes_service = PaperReaderNotesApplicationService(store_path=tmp_path / "reader-notes.json")
    first_session = auth_service.bootstrap(username="admin", password="correct horse")
    auth_service._create_user(username="reader2", password="correct horse", role="admin")
    second_session = auth_service.login(username="reader2", password="correct horse")
    assert first_session.sessionToken is not None
    assert second_session.sessionToken is not None

    client = TestClient(
        create_app(
            auth_service_factory=lambda: auth_service,
            paper_reader_notes_service_factory=lambda: notes_service,
            audit_emitter_factory=None,
        )
    )

    unauthenticated = client.get("/api/v1/papers/paper-1/notes")
    assert unauthenticated.status_code == 401
    assert unauthenticated.json()["error"]["code"] == "auth_session_required"

    invalid = client.post(
        "/api/v1/papers/paper-1/notes",
        json={"kind": "highlight", "pageNumber": 0, "quote": "x"},
        headers={"x-newsroom-session": first_session.sessionToken},
    )
    assert invalid.status_code in {400, 422}

    created = client.post(
        "/api/v1/papers/paper-1/notes",
        json={
            "kind": "note",
            "pageNumber": 2,
            "color": "green",
            "quote": "Selected public text",
            "noteText": "Useful implementation caveat.",
            "anchor": {
                "pageNumber": 2,
                "quote": "Selected public text",
                "rects": [{"left": 10, "top": 20, "width": 100, "height": 14}],
                "secret": "drop me",
            },
            "token": "drop me too",
        },
        headers={"x-newsroom-session": first_session.sessionToken},
    )
    assert created.status_code == 200
    note = created.json()["data"]["note"]
    note_id = note["noteId"]
    assert note["kind"] == "note"
    assert note["pageNumber"] == 2
    assert note["color"] == "green"
    assert note["anchor"]["rects"][0]["width"] == 100.0
    serialized = json.dumps(created.json())
    assert "token" not in serialized
    assert "secret" not in serialized

    listed = client.get(
        "/api/v1/papers/paper-1/notes",
        headers={"x-newsroom-session": first_session.sessionToken},
    )
    assert listed.status_code == 200
    assert [item["noteId"] for item in listed.json()["data"]["notes"]] == [note_id]

    second_user_list = client.get(
        "/api/v1/papers/paper-1/notes",
        headers={"x-newsroom-session": second_session.sessionToken},
    )
    assert second_user_list.status_code == 200
    assert second_user_list.json()["data"]["notes"] == []

    cross_user_patch = client.patch(
        f"/api/v1/papers/paper-1/notes/{note_id}",
        json={"noteText": "nope"},
        headers={"x-newsroom-session": second_session.sessionToken},
    )
    assert cross_user_patch.status_code == 404
    assert cross_user_patch.json()["error"]["code"] == "paper_reader_note_not_found"

    patched = client.patch(
        f"/api/v1/papers/paper-1/notes/{note_id}",
        json={"color": "pink", "noteText": "Updated note."},
        headers={"x-newsroom-session": first_session.sessionToken},
    )
    assert patched.status_code == 200
    assert patched.json()["data"]["note"]["color"] == "pink"
    assert patched.json()["data"]["note"]["noteText"] == "Updated note."

    deleted = client.delete(
        f"/api/v1/papers/paper-1/notes/{note_id}",
        headers={"x-newsroom-session": first_session.sessionToken},
    )
    assert deleted.status_code == 200
    assert deleted.json()["data"]["deleted"] is True

    missing = client.delete(
        f"/api/v1/papers/paper-1/notes/{note_id}",
        headers={"x-newsroom-session": first_session.sessionToken},
    )
    assert missing.status_code == 404
