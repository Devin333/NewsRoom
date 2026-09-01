from __future__ import annotations

from fastapi.testclient import TestClient

from interfaces.api import create_app
from interfaces.services.project_service import (
    ProjectLabAnswerValidationError,
    ProjectLabQuestionNotFoundError,
    ProjectLabSessionNotReadyError,
    ProjectLabSolutionMissingError,
)


def test_projects_api_registers_product_routes_with_envelope() -> None:
    service = _FakeProjectApplicationService()
    client = TestClient(create_app(project_service_factory=lambda: service, audit_emitter_factory=None))

    response = client.get("/api/v1/projects", headers={"X-Request-ID": "req-projects"})
    payload = response.json()

    assert response.status_code == 200
    assert response.headers["X-Request-ID"] == "req-projects"
    assert payload["success"] is True
    assert payload["request_id"] == "req-projects"
    assert payload["data"]["hot"][0]["id"] == "project-1"
    assert payload["ok"] is True
    assert service.calls[0] == ("get_home", {"limit": 6, "user_id": "anonymous"})


def test_projects_api_hot_rising_tools_cases_collections_and_detail_routes() -> None:
    service = _FakeProjectApplicationService()
    client = TestClient(create_app(project_service_factory=lambda: service, audit_emitter_factory=None))

    paths = [
        "/api/v1/projects/hot",
        "/api/v1/projects/rising",
        "/api/v1/projects/tools",
        "/api/v1/projects/tools/project-1",
        "/api/v1/projects/cases",
        "/api/v1/projects/cases/case-1",
        "/api/v1/projects/collections",
        "/api/v1/projects/collections/collection-1",
        "/api/v1/projects/lab/sessions/session-1",
        "/api/v1/projects/evolution/proposals",
        "/api/v1/projects/project-1",
    ]

    for path in paths:
        response = client.get(path)
        assert response.status_code == 200, path
        assert response.json()["success"] is True, path


def test_projects_api_mutation_routes_use_service_boundary() -> None:
    service = _FakeProjectApplicationService()
    client = TestClient(create_app(project_service_factory=lambda: service, audit_emitter_factory=None))

    compare = client.post("/api/v1/projects/tools/compare", json={"project_ids": ["project-1"]})
    recommend = client.post("/api/v1/projects/tools/recommend", json={"problem": "Need agent workflow", "limit": 1})
    session = client.post("/api/v1/projects/lab/sessions", json={"user_problem": "Need agent workflow"})
    answer = client.post(
        "/api/v1/projects/lab/sessions/session-1/answer",
        json={"question_id": "question-1", "answer": "release cadence"},
    )
    solution = client.post("/api/v1/projects/lab/sessions/session-1/generate-solution")
    explain_node = client.post(
        "/api/v1/projects/lab/sessions/session-1/explain-node",
        json={"node_id": "node-1"},
    )
    save_session = client.post("/api/v1/projects/lab/sessions/session-1/save", json={"status": "saved"})
    explain_case = client.post("/api/v1/projects/cases/case-1/explain", json={"style": "plain"})
    map_case = client.post(
        "/api/v1/projects/cases/case-1/map-to-context",
        json={"user_context": "Need workflow design"},
    )
    create_collection = client.post(
        "/api/v1/projects/collections",
        json={"title": "Workflow Picks", "description": "Real project collection."},
    )
    add_collection_item = client.post(
        "/api/v1/projects/collections/collection-1/items",
        json={"item_type": "project", "item_id": "project-1", "title": "Project One", "reason": "Relevant."},
    )
    generate_collection = client.post("/api/v1/projects/collections/generate", json={"topic": "workflow"})
    add_watch = client.post(
        "/api/v1/projects/watchlist",
        json={"project_id": "project-1", "watch_reason": "Track releases"},
    )
    patch_watch = client.patch("/api/v1/projects/watchlist/watch-1", json={"priority": "high"})
    refresh_watch = client.post("/api/v1/projects/watchlist/watch-1/refresh")
    delete_watch = client.delete("/api/v1/projects/watchlist/watch-1")
    event = client.post(
        "/api/v1/projects/interactions",
        json={"event_type": "view", "target_type": "project", "target_id": "project-1"},
    )

    for response in [
        compare,
        recommend,
        session,
        answer,
        solution,
        explain_node,
        save_session,
        explain_case,
        map_case,
        create_collection,
        add_collection_item,
        generate_collection,
        add_watch,
        patch_watch,
        refresh_watch,
        delete_watch,
        event,
    ]:
        assert response.status_code == 200
        assert response.json()["success"] is True
        assert response.json()["ok"] is True

    assert ("compare_tools", {"project_ids": ["project-1"]}) in service.calls
    assert ("record_interaction", {"event_type": "view", "target_id": "project-1"}) in service.calls
    assert ("patch_watchlist", {"item_id": "watch-1", "priority": "high", "user_id": "anonymous"}) in service.calls


def test_projects_api_not_found_errors_use_standard_envelope() -> None:
    service = _FakeProjectApplicationService(not_found=True)
    client = TestClient(create_app(project_service_factory=lambda: service, audit_emitter_factory=None))

    response = client.get("/api/v1/projects/missing", headers={"X-Request-ID": "req-missing"})
    payload = response.json()

    assert response.status_code == 404
    assert payload["success"] is False
    assert payload["ok"] is False
    assert payload["request_id"] == "req-missing"
    assert payload["error"]["code"] == "project_not_found"


def test_projects_api_lab_contract_errors_use_status_specific_envelopes() -> None:
    service = _FakeProjectApplicationService()
    client = TestClient(create_app(project_service_factory=lambda: service, audit_emitter_factory=None))

    service.lab_answer_error = ProjectLabQuestionNotFoundError("project lab question not found")
    response = client.post(
        "/api/v1/projects/lab/sessions/session-1/answer",
        json={"question_id": "missing", "answer": "value"},
    )
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "project_lab_question_not_found"

    service.lab_answer_error = ProjectLabAnswerValidationError("answer must be a non-empty string")
    response = client.post(
        "/api/v1/projects/lab/sessions/session-1/answer",
        json={"question_id": "question-1", "answer": "   "},
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_project_lab_answer"

    service.lab_answer_error = None
    service.lab_generate_error = ProjectLabSessionNotReadyError(["question-1", "question-2"])
    response = client.post("/api/v1/projects/lab/sessions/session-1/generate-solution")
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "lab_session_not_ready"
    assert response.json()["error"]["details"]["unanswered_question_ids"] == ["question-1", "question-2"]

    service.lab_generate_error = None
    service.lab_save_error = ProjectLabSolutionMissingError("project lab solution is required before saving a session")
    response = client.post("/api/v1/projects/lab/sessions/session-1/save", json={"status": "saved"})
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "lab_solution_missing"


class _FakeProjectApplicationService:
    def __init__(self, *, not_found: bool = False) -> None:
        self.not_found = not_found
        self.calls = []
        self.lab_answer_error = None
        self.lab_generate_error = None
        self.lab_save_error = None

    def get_home(self, *, limit=6, user_id=None):
        self.calls.append(("get_home", {"limit": limit, "user_id": user_id}))
        return {
            "hot": [_project()],
            "rising": [_project()],
            "tools": [_project()],
            "cases": [_case()],
            "collections": [_collection()],
            "watchlist": [],
            "recommendations": [],
            "meta": _meta(),
            "metrics": [],
        }

    def list_hot(self, query):
        self.calls.append(("list_hot", {"limit": query.limit}))
        return {"items": [_project()], "page": _page(), "meta": _meta(), "metrics": []}

    def list_rising(self, query):
        self.calls.append(("list_rising", {"limit": query.limit}))
        return {"items": [_project()], "page": _page(), "meta": _meta(), "metrics": []}

    def get_project(self, project_id):
        self.calls.append(("get_project", {"project_id": project_id}))
        if self.not_found:
            from interfaces.services.project_service import ProjectNotFoundError

            raise ProjectNotFoundError("project not found: missing")
        return {"project": _project(), "sources": [], "metrics": [], "growth": [], "capabilities": [], "tool_profile": None, "cases": [], "meta": _meta()}

    def search_tools(self, query):
        self.calls.append(("search_tools", {"limit": query.limit}))
        return {"tools": [{"project": _project(), "profile": {"project_id": "project-1", "tool_type": "workflow"}, "capabilities": []}], "page": _page(), "meta": _meta()}

    def get_tool_detail(self, project_id):
        self.calls.append(("get_tool_detail", {"project_id": project_id}))
        return {"project": _project(), "profile": {"project_id": project_id, "tool_type": "workflow"}, "capabilities": []}

    def compare_tools(self, request):
        self.calls.append(("compare_tools", {"project_ids": request.project_ids}))
        return {"tools": [], "matrix": [], "recommendation": None, "meta": _meta()}

    def recommend_tools(self, request):
        self.calls.append(("recommend_tools", {"problem": request.problem}))
        return {"tools": [], "reasoning": [], "meta": _meta()}

    def search_cases(self, query):
        self.calls.append(("search_cases", {"limit": query.limit}))
        return {"cases": [_case()], "page": _page(), "meta": _meta()}

    def get_case_detail(self, case_id):
        self.calls.append(("get_case_detail", {"case_id": case_id}))
        return _case()

    def explain_case(self, case_id, request):
        self.calls.append(("explain_case", {"case_id": case_id, "style": request.style}))
        return {"case_id": case_id, "style": request.style, "summary": "Plain case explanation.", "source_refs": []}

    def map_case_to_context(self, case_id, request):
        self.calls.append(("map_case_to_context", {"case_id": case_id, "user_context": request.user_context}))
        return {"case_id": case_id, "fit_score": 0.8, "migration_steps": ["Reuse source-backed component."]}

    def list_collections(self):
        self.calls.append(("list_collections", {}))
        return {"collections": [_collection()], "meta": _meta()}

    def get_collection(self, slug):
        self.calls.append(("get_collection", {"slug": slug}))
        return _collection()

    def create_collection(self, request):
        self.calls.append(("create_collection", {"title": request.title, "created_by": request.created_by}))
        return {"collection": _collection(), "meta": _meta()}

    def add_collection_item(self, collection_id, request):
        self.calls.append(("add_collection_item", {"collection_id": collection_id, "item_type": request.item_type}))
        return {"collection": _collection(), "meta": _meta()}

    def generate_collection(self, request):
        self.calls.append(("generate_collection", {"topic": request.topic, "created_by": request.created_by}))
        return {"collection": _collection(), "meta": _meta()}

    def start_lab_session(self, request):
        self.calls.append(("start_lab_session", {"user_problem": request.user_problem, "user_id": request.user_id}))
        return _session()

    def get_lab_session(self, session_id):
        self.calls.append(("get_lab_session", {"session_id": session_id}))
        return _session()

    def answer_lab_question(self, session_id, request):
        if self.lab_answer_error is not None:
            raise self.lab_answer_error
        self.calls.append(("answer_lab_question", {"session_id": session_id, "question_id": request.question_id}))
        return _session()

    def generate_lab_solution(self, session_id):
        if self.lab_generate_error is not None:
            raise self.lab_generate_error
        self.calls.append(("generate_lab_solution", {"session_id": session_id}))
        return {"session": _session(), "solution": {"id": "solution-1"}}

    def explain_lab_node(self, session_id, request):
        self.calls.append(("explain_lab_node", {"session_id": session_id, "node_id": request.node_id}))
        return {"session_id": session_id, "node_id": request.node_id, "title": "Node", "explanation": "Node explanation."}

    def save_lab_session(self, session_id, request):
        if self.lab_save_error is not None:
            raise self.lab_save_error
        self.calls.append(("save_lab_session", {"session_id": session_id, "status": request.status}))
        return _session()

    def list_watchlist(self, *, user_id=None):
        self.calls.append(("list_watchlist", {"user_id": user_id}))
        return {"items": [], "meta": _meta()}

    def add_watchlist(self, request):
        self.calls.append(("add_watchlist", {"project_id": request.project_id}))
        return {"id": "watch-1", "user_id": "anonymous", "project_id": request.project_id, "watch_reason": request.watch_reason, "status": "active"}

    def patch_watchlist(self, item_id, request, *, user_id=None):
        self.calls.append(("patch_watchlist", {"item_id": item_id, "priority": request.priority, "user_id": user_id}))
        return {"id": item_id, "user_id": "anonymous", "project_id": "project-1", "watch_reason": "Track", "priority": request.priority, "status": "active"}

    def refresh_watchlist(self, item_id, *, user_id=None):
        self.calls.append(("refresh_watchlist", {"item_id": item_id, "user_id": user_id}))
        return {"item": {"id": item_id, "user_id": "anonymous", "project_id": "project-1", "watch_reason": "Track"}, "signals": [], "meta": _meta()}

    def delete_watchlist(self, item_id, *, user_id=None):
        self.calls.append(("delete_watchlist", {"item_id": item_id, "user_id": user_id}))
        return {"deleted": True, "item_id": item_id}

    def record_interaction(self, request):
        self.calls.append(("record_interaction", {"event_type": request.event_type, "target_id": request.target_id}))
        return {"id": "event-1", "event_type": request.event_type, "target_type": request.target_type, "target_id": request.target_id}

    def list_evolution_proposals(self):
        self.calls.append(("list_evolution_proposals", {}))
        return {"proposals": []}


def _project():
    return {"id": "project-1", "slug": "project-1", "name": "Project One", "project_type": "tool", "source_confidence": 0.9}


def _case():
    return {"id": "case-1", "project_id": "project-1", "title": "Case One", "business_domain": "engineering", "module_type": "workflow"}


def _collection():
    return {"id": "collection-1", "slug": "collection-1", "title": "Collection One", "description": "Real-derived collection."}


def _session():
    return {"id": "session-1", "user_problem": "Need agent workflow", "graph_state": {"session_id": "session-1", "nodes": [{"id": "node-1"}]}, "questions": [], "status": "active"}


def _meta():
    return {"source": "artifact", "source_run_id": "run-project-radar", "data_state": "ready", "notices": []}


def _page():
    return {"page": 1, "page_size": 24, "total": 1, "has_next": False}
