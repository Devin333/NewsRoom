from __future__ import annotations

from fastapi.testclient import TestClient

from interfaces.api import create_app


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
    assert service.calls[0] == ("get_home", {"limit": 6, "user_id": None})


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
    add_watch = client.post(
        "/api/v1/projects/watchlist",
        json={"project_id": "project-1", "watch_reason": "Track releases"},
    )
    patch_watch = client.patch("/api/v1/projects/watchlist/watch-1", json={"priority": "high"})
    delete_watch = client.delete("/api/v1/projects/watchlist/watch-1")
    event = client.post(
        "/api/v1/projects/interactions",
        json={"event_type": "view", "target_type": "project", "target_id": "project-1"},
    )

    for response in [compare, recommend, session, answer, solution, add_watch, patch_watch, delete_watch, event]:
        assert response.status_code == 200
        assert response.json()["success"] is True

    assert ("compare_tools", {"project_ids": ["project-1"]}) in service.calls
    assert ("record_interaction", {"event_type": "view", "target_id": "project-1"}) in service.calls


def test_projects_api_not_found_errors_use_standard_envelope() -> None:
    service = _FakeProjectApplicationService(not_found=True)
    client = TestClient(create_app(project_service_factory=lambda: service, audit_emitter_factory=None))

    response = client.get("/api/v1/projects/missing", headers={"X-Request-ID": "req-missing"})
    payload = response.json()

    assert response.status_code == 404
    assert payload["success"] is False
    assert payload["request_id"] == "req-missing"
    assert payload["error"]["code"] == "project_not_found"


class _FakeProjectApplicationService:
    def __init__(self, *, not_found: bool = False) -> None:
        self.not_found = not_found
        self.calls = []

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

    def list_collections(self):
        self.calls.append(("list_collections", {}))
        return {"collections": [_collection()], "meta": _meta()}

    def get_collection(self, slug):
        self.calls.append(("get_collection", {"slug": slug}))
        return _collection()

    def start_lab_session(self, request):
        self.calls.append(("start_lab_session", {"user_problem": request.user_problem}))
        return _session()

    def answer_lab_question(self, session_id, request):
        self.calls.append(("answer_lab_question", {"session_id": session_id, "question_id": request.question_id}))
        return _session()

    def generate_lab_solution(self, session_id):
        self.calls.append(("generate_lab_solution", {"session_id": session_id}))
        return {"session": _session(), "solution": {"id": "solution-1"}}

    def list_watchlist(self, *, user_id=None):
        self.calls.append(("list_watchlist", {"user_id": user_id}))
        return {"items": [], "meta": _meta()}

    def add_watchlist(self, request):
        self.calls.append(("add_watchlist", {"project_id": request.project_id}))
        return {"id": "watch-1", "user_id": "anonymous", "project_id": request.project_id, "watch_reason": request.watch_reason, "status": "active"}

    def patch_watchlist(self, item_id, request):
        self.calls.append(("patch_watchlist", {"item_id": item_id, "priority": request.priority}))
        return {"id": item_id, "user_id": "anonymous", "project_id": "project-1", "watch_reason": "Track", "priority": request.priority, "status": "active"}

    def delete_watchlist(self, item_id):
        self.calls.append(("delete_watchlist", {"item_id": item_id}))
        return {"deleted": True, "item_id": item_id}

    def record_interaction(self, request):
        self.calls.append(("record_interaction", {"event_type": request.event_type, "target_id": request.target_id}))
        return {"id": "event-1", "event_type": request.event_type, "target_type": request.target_type, "target_id": request.target_id}


def _project():
    return {"id": "project-1", "slug": "project-1", "name": "Project One", "project_type": "tool", "source_confidence": 0.9}


def _case():
    return {"id": "case-1", "project_id": "project-1", "title": "Case One", "business_domain": "engineering", "module_type": "workflow"}


def _collection():
    return {"id": "collection-1", "slug": "collection-1", "title": "Collection One", "description": "Real-derived collection."}


def _session():
    return {"id": "session-1", "user_problem": "Need agent workflow", "graph_state": {"session_id": "session-1"}, "questions": [], "status": "active"}


def _meta():
    return {"source": "artifact", "source_run_id": "run-project-radar", "data_state": "ready", "notices": []}


def _page():
    return {"page": 1, "page_size": 24, "total": 1, "has_next": False}
