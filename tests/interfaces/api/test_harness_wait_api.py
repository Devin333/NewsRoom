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
from interfaces.api import create_app
from interfaces.models import ActorContext
from interfaces.services.harness_wait_service import (
    HarnessWaitApplicationError,
    HarnessWaitAuthorizationError,
    HarnessWaitInspectionResult,
    HarnessWaitNotFoundError,
    HarnessWaitOperationResult,
    HarnessWaitRequestError,
)


_TOKEN = "harness-wait-secret"
_AUTH_HEADERS = {"Authorization": f"Bearer {_TOKEN}"}
_WAIT_PATH = "/api/v1/runs/run-1/waits/node-1"


@dataclass
class _FakeHarnessWaitService:
    failure: Exception | None = None
    calls: list[tuple[str, dict[str, Any]]] = field(default_factory=list)

    def inspect_wait(
        self,
        run_id: str,
        node_instance_id: str,
    ) -> HarnessWaitInspectionResult:
        self._record(
            "inspect",
            run_id=run_id,
            node_instance_id=node_instance_id,
        )
        return _inspection(run_id, node_instance_id)

    def deliver_signal(
        self,
        run_id: str,
        node_instance_id: str,
        **arguments: Any,
    ) -> HarnessWaitOperationResult:
        self._record(
            "signal",
            run_id=run_id,
            node_instance_id=node_instance_id,
            **arguments,
        )
        return _operation("signal", run_id, node_instance_id)

    def decide_approval(
        self,
        run_id: str,
        node_instance_id: str,
        **arguments: Any,
    ) -> HarnessWaitOperationResult:
        self._record(
            "approval",
            run_id=run_id,
            node_instance_id=node_instance_id,
            **arguments,
        )
        return _operation("approval", run_id, node_instance_id)

    def cancel_wait(
        self,
        run_id: str,
        node_instance_id: str,
        **arguments: Any,
    ) -> HarnessWaitOperationResult:
        self._record(
            "cancellation",
            run_id=run_id,
            node_instance_id=node_instance_id,
            **arguments,
        )
        return _operation("cancellation", run_id, node_instance_id)

    def _record(self, operation: str, **arguments: Any) -> None:
        self.calls.append((operation, arguments))
        if self.failure is not None:
            raise self.failure


@dataclass
class _CapturingFactory:
    service: _FakeHarnessWaitService
    actors: list[ActorContext] = field(default_factory=list)

    def __call__(self, actor: ActorContext) -> _FakeHarnessWaitService:
        self.actors.append(actor)
        return self.service


def test_harness_wait_routes_bind_authenticated_actor_and_delegate_operations() -> None:
    client, service, factory = _client()

    responses = (
        client.get(_WAIT_PATH, headers=_AUTH_HEADERS),
        client.post(
            f"{_WAIT_PATH}/signals",
            headers=_AUTH_HEADERS,
            json={
                "signal_id": "signal-1",
                "signal_schema_ref": "newsroom.wait@1",
                "correlation": {"request_id": "request-1"},
                "payload_ref": f"sha256:{'a' * 64}",
            },
        ),
        client.post(
            f"{_WAIT_PATH}/approval",
            headers=_AUTH_HEADERS,
            json={"approval_id": "approval-1", "approved": True},
        ),
        client.post(
            f"{_WAIT_PATH}/cancel",
            headers=_AUTH_HEADERS,
            json={
                "cancellation_id": "cancel-1",
                "reason_code": "operator_cancelled",
            },
        ),
    )

    assert [response.status_code for response in responses] == [200, 200, 200, 200]
    assert [response.json()["data"].get("operation") for response in responses] == [
        None,
        "signal",
        "approval",
        "cancellation",
    ]
    expected_actor_id = f"api-key:{hashlib.sha256(_TOKEN.encode()).hexdigest()}"
    assert [actor.actor_id for actor in factory.actors] == [expected_actor_id] * 4
    assert all(actor.roles == ["admin"] for actor in factory.actors)
    assert service.calls == [
        ("inspect", {"run_id": "run-1", "node_instance_id": "node-1"}),
        (
            "signal",
            {
                "run_id": "run-1",
                "node_instance_id": "node-1",
                "signal_id": "signal-1",
                "signal_schema_ref": "newsroom.wait@1",
                "correlation": {"request_id": "request-1"},
                "payload_ref": f"sha256:{'a' * 64}",
            },
        ),
        (
            "approval",
            {
                "run_id": "run-1",
                "node_instance_id": "node-1",
                "approval_id": "approval-1",
                "approved": True,
            },
        ),
        (
            "cancellation",
            {
                "run_id": "run-1",
                "node_instance_id": "node-1",
                "cancellation_id": "cancel-1",
                "reason_code": "operator_cancelled",
            },
        ),
    ]


@pytest.mark.parametrize("forged_field", ("tenant", "identity", "actor", "decided_by"))
def test_harness_wait_request_bodies_reject_forged_authority_fields(
    forged_field: str,
) -> None:
    client, service, factory = _client()
    body = {
        "signal_id": "signal-1",
        "signal_schema_ref": "newsroom.wait@1",
        "correlation": {"request_id": "request-1"},
        "payload_ref": f"sha256:{'a' * 64}",
        forged_field: "forged",
    }

    response = client.post(
        f"{_WAIT_PATH}/signals",
        headers=_AUTH_HEADERS,
        json=body,
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_request"
    assert factory.actors == []
    assert service.calls == []


def test_harness_wait_route_never_builds_actor_from_spoofable_headers() -> None:
    service = _FakeHarnessWaitService()
    factory = _CapturingFactory(service)
    client = TestClient(
        create_app(
            harness_wait_service_factory=factory,
            audit_emitter_factory=None,
        )
    )

    response = client.get(
        _WAIT_PATH,
        headers={
            "X-News-Actor": "forged-operator",
            "X-News-Roles": "admin",
        },
    )

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthorized"
    assert factory.actors == []


def test_harness_wait_route_returns_503_when_factory_is_not_configured() -> None:
    client = TestClient(
        create_app(
            api_keys={_TOKEN: ["admin"]},
            audit_emitter_factory=None,
        )
    )

    response = client.get(_WAIT_PATH, headers=_AUTH_HEADERS)

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "harness_wait_capability_unavailable"


def test_harness_wait_approval_uses_manage_approvals_middleware_permission() -> None:
    reviewer_client, reviewer_service, _ = _client(roles=["reviewer"])
    developer_client, developer_service, developer_factory = _client(
        roles=["developer"]
    )

    accepted = reviewer_client.post(
        f"{_WAIT_PATH}/approval",
        headers=_AUTH_HEADERS,
        json={"approval_id": "approval-1", "approved": True},
    )
    denied = developer_client.post(
        f"{_WAIT_PATH}/approval",
        headers=_AUTH_HEADERS,
        json={"approval_id": "approval-1", "approved": True},
    )

    assert accepted.status_code == 200
    assert reviewer_service.calls[0][0] == "approval"
    assert denied.status_code == 403
    assert denied.json()["error"]["details"]["required_permission"] == (
        "manage:approvals"
    )
    assert developer_factory.actors == []
    assert developer_service.calls == []


def test_harness_wait_inspection_uses_read_permission() -> None:
    client, service, factory = _client(roles=["viewer"])

    response = client.get(_WAIT_PATH, headers=_AUTH_HEADERS)

    assert response.status_code == 200
    assert service.calls[0][0] == "inspect"
    assert len(factory.actors) == 1


@pytest.mark.parametrize(
    ("suffix", "body"),
    (
        (
            "signals",
            {
                "signal_id": "signal-1",
                "signal_schema_ref": "newsroom.wait@1",
                "correlation": {"request_id": "request-1"},
                "payload_ref": f"sha256:{'a' * 64}",
            },
        ),
        (
            "cancel",
            {
                "cancellation_id": "cancel-1",
                "reason_code": "operator_cancelled",
            },
        ),
    ),
)
def test_harness_wait_mutations_use_write_permission(
    suffix: str,
    body: dict[str, object],
) -> None:
    client, service, factory = _client(roles=["viewer"])

    response = client.post(
        f"{_WAIT_PATH}/{suffix}",
        headers=_AUTH_HEADERS,
        json=body,
    )

    assert response.status_code == 403
    assert response.json()["error"]["details"]["required_permission"] == ("write:runs")
    assert factory.actors == []
    assert service.calls == []


def test_harness_wait_router_has_no_control_plane_or_store_dependency() -> None:
    router_path = (
        Path(__file__).resolve().parents[3]
        / "interfaces"
        / "api"
        / "routers"
        / "harness_waits.py"
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
            "accept_graph_wait_cause",
            "recover_and_run",
            "recover_graph",
            "read_stream",
            "append",
        }
    )


@pytest.mark.parametrize(
    ("failure", "expected_status", "expected_code"),
    (
        (
            HarnessWaitAuthorizationError("denied", code="wait_permission_denied"),
            403,
            "forbidden",
        ),
        (
            HarnessWaitNotFoundError("missing", code="wait_not_found"),
            404,
            "wait_not_found",
        ),
        (
            HarnessWaitRequestError("conflict", code="wait_signal_conflict"),
            409,
            "wait_signal_conflict",
        ),
        (
            HarnessValidationError("durable conflict", code="graph_wait_conflict"),
            409,
            "graph_wait_conflict",
        ),
        (
            EventStoreUnavailableError("offline"),
            503,
            "event_store_unavailable",
        ),
        (
            HarnessWaitApplicationError(
                "resolver missing",
                code="wait_runtime_resolver_missing",
            ),
            503,
            "wait_runtime_resolver_missing",
        ),
    ),
)
def test_harness_wait_application_errors_have_stable_http_mapping(
    failure: Exception,
    expected_status: int,
    expected_code: str,
) -> None:
    client, _, _ = _client(_FakeHarnessWaitService(failure=failure))

    response = client.get(_WAIT_PATH, headers=_AUTH_HEADERS)

    assert response.status_code == expected_status
    assert response.json()["error"]["code"] == expected_code


def _client(
    service: _FakeHarnessWaitService | None = None,
    *,
    roles: list[str] | None = None,
) -> tuple[TestClient, _FakeHarnessWaitService, _CapturingFactory]:
    fake = service or _FakeHarnessWaitService()
    factory = _CapturingFactory(fake)
    client = TestClient(
        create_app(
            api_keys={_TOKEN: roles or ["admin"]},
            harness_wait_service_factory=factory,
            audit_emitter_factory=None,
        )
    )
    return client, fake, factory


def _inspection(run_id: str, node_instance_id: str) -> HarnessWaitInspectionResult:
    return HarnessWaitInspectionResult(
        run_id=run_id,
        node_instance_id=node_instance_id,
        wait_id="wait-1",
        kind="signal",
        status="registered",
        signal_schema_ref="newsroom.wait@1",
        lifecycle="waiting",
        outcome="none",
        registered_sequence=3,
        last_event_sequence=3,
    )


def _operation(
    operation: str,
    run_id: str,
    node_instance_id: str,
) -> HarnessWaitOperationResult:
    return HarnessWaitOperationResult(
        operation=operation,
        wait=_inspection(run_id, node_instance_id),
    )
