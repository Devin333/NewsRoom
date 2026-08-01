from __future__ import annotations

import ast
import hashlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from framework.events import EventStoreUnavailableError
from framework.harness import HarnessValidationError
from framework.harness.control_plane.graph_inspection import HarnessGraphInspection
from framework.harness.control_plane.graph_observability import (
    HarnessGraphHealthReport,
)
from interfaces.api import create_app
from interfaces.models import ActorContext
from interfaces.services.harness_graph_service import (
    HarnessGraphApplicationError,
    HarnessGraphAuthorizationError,
    HarnessGraphNotFoundError,
)


_TOKEN = "harness-graph-secret"
_AUTH_HEADERS = {"Authorization": f"Bearer {_TOKEN}"}
_GRAPH_PATH = "/api/v1/runs/run-1/graph"


@dataclass
class _FakeHarnessGraphService:
    failure: Exception | None = None
    calls: list[tuple[str, dict[str, Any]]] = field(default_factory=list)

    def inspect_run(
        self,
        run_id: str,
        *,
        verify_history: bool = False,
    ) -> HarnessGraphInspection:
        self._record(
            "inspect",
            run_id=run_id,
            verify_history=verify_history,
        )
        return HarnessGraphInspection(
            {
                "schema_version": "newsroom.harness-graph-inspection/v1",
                "run_id": run_id,
                "lifecycle": "running",
                "outcome": "none",
                "projection_checksum": f"sha256:{'a' * 64}",
                "payload_refs": [f"sha256:{'b' * 64}"],
            }
        )

    def inspect_health(self, run_id: str) -> HarnessGraphHealthReport:
        self._record("health", run_id=run_id)
        return HarnessGraphHealthReport("healthy", (), 7)

    def _record(self, operation: str, **arguments: Any) -> None:
        self.calls.append((operation, arguments))
        if self.failure is not None:
            raise self.failure


@dataclass
class _CapturingFactory:
    service: _FakeHarnessGraphService
    actors: list[ActorContext] = field(default_factory=list)

    def __call__(self, actor: ActorContext) -> _FakeHarnessGraphService:
        self.actors.append(actor)
        return self.service


def test_graph_routes_bind_actor_and_delegate_inspection_and_health() -> None:
    client, service, factory = _client()

    inspection = client.get(
        f"{_GRAPH_PATH}?verify_history=true",
        headers=_AUTH_HEADERS,
    )
    health = client.get(f"{_GRAPH_PATH}/health", headers=_AUTH_HEADERS)

    assert inspection.status_code == 200
    assert health.status_code == 200
    assert inspection.json()["data"]["lifecycle"] == "running"
    assert health.json()["data"] == {
        "status": "healthy",
        "diagnostics": [],
        "last_event_sequence": 7,
    }
    expected_actor_id = f"api-key:{hashlib.sha256(_TOKEN.encode()).hexdigest()}"
    assert [actor.actor_id for actor in factory.actors] == [expected_actor_id] * 2
    assert all(actor.roles == ["admin"] for actor in factory.actors)
    assert service.calls == [
        ("inspect", {"run_id": "run-1", "verify_history": True}),
        ("health", {"run_id": "run-1"}),
    ]


def test_graph_route_rejects_spoofed_actor_headers() -> None:
    service = _FakeHarnessGraphService()
    factory = _CapturingFactory(service)
    client = TestClient(
        create_app(
            harness_graph_service_factory=factory,
            audit_emitter_factory=None,
        )
    )

    response = client.get(
        _GRAPH_PATH,
        headers={
            "X-News-Actor": "forged-operator",
            "X-News-Roles": "admin",
        },
    )

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthorized"
    assert factory.actors == []
    assert service.calls == []


def test_graph_route_returns_503_when_capability_is_not_configured() -> None:
    client = TestClient(
        create_app(
            api_keys={_TOKEN: ["admin"]},
            audit_emitter_factory=None,
        )
    )

    response = client.get(_GRAPH_PATH, headers=_AUTH_HEADERS)

    assert response.status_code == 503
    assert response.json()["error"]["code"] == ("harness_graph_capability_unavailable")


def test_graph_inspection_uses_read_permission() -> None:
    client, service, factory = _client(roles=["viewer"])

    response = client.get(_GRAPH_PATH, headers=_AUTH_HEADERS)

    assert response.status_code == 200
    assert service.calls[0][0] == "inspect"
    assert len(factory.actors) == 1


def test_graph_router_has_no_control_plane_or_store_dependency() -> None:
    router_path = (
        Path(__file__).resolve().parents[3]
        / "interfaces"
        / "api"
        / "routers"
        / "harness_graph.py"
    )
    tree = ast.parse(router_path.read_text(encoding="utf-8"))
    imported_modules: set[str] = set()
    called_attributes: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            imported_modules.add(node.module)
        elif isinstance(node, ast.Import):
            imported_modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            called_attributes.add(node.func.attr)

    forbidden_import_prefixes = (
        "framework.harness.control_plane",
        "framework.events.store",
        "infrastructure",
    )
    assert not any(
        module.startswith(forbidden_import_prefixes) for module in imported_modules
    )
    assert called_attributes.isdisjoint(
        {
            "recover_graph",
            "verify_graph_history",
            "read_stream",
            "append",
        }
    )


@pytest.mark.parametrize(
    ("failure", "expected_status", "expected_code"),
    (
        (
            HarnessGraphAuthorizationError(
                "denied",
                code="graph_inspection_permission_denied",
            ),
            403,
            "forbidden",
        ),
        (
            HarnessGraphNotFoundError("missing", code="graph_run_not_found"),
            404,
            "graph_run_not_found",
        ),
        (
            HarnessValidationError(
                "history mismatch",
                code="graph_replay_checksum_mismatch",
            ),
            409,
            "graph_replay_checksum_mismatch",
        ),
        (
            EventStoreUnavailableError("offline"),
            503,
            "event_store_unavailable",
        ),
        (
            HarnessGraphApplicationError(
                "resolver missing",
                code="graph_runtime_resolver_missing",
            ),
            503,
            "graph_runtime_resolver_missing",
        ),
    ),
)
def test_graph_application_errors_have_stable_http_mapping(
    failure: Exception,
    expected_status: int,
    expected_code: str,
) -> None:
    client, _, _ = _client(_FakeHarnessGraphService(failure=failure))

    response = client.get(_GRAPH_PATH, headers=_AUTH_HEADERS)

    assert response.status_code == expected_status
    assert response.json()["error"]["code"] == expected_code


def _client(
    service: _FakeHarnessGraphService | None = None,
    *,
    roles: list[str] | None = None,
) -> tuple[TestClient, _FakeHarnessGraphService, _CapturingFactory]:
    fake = service or _FakeHarnessGraphService()
    factory = _CapturingFactory(fake)
    client = TestClient(
        create_app(
            api_keys={_TOKEN: roles or ["admin"]},
            harness_graph_service_factory=factory,
            audit_emitter_factory=None,
        )
    )
    return client, fake, factory
