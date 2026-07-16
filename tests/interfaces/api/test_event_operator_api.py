from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Any

import pytest
from fastapi.testclient import TestClient

from framework.events.errors import EventContractError, EventStoreUnavailableError
from interfaces.api import create_app
from interfaces.models import ActorContext
from interfaces.services.event_delivery_operations_service import (
    EventOperationNotFoundError,
)
from interfaces.services.event_operator_service import (
    EventOperationCapabilityUnavailableError,
)
from interfaces.services.event_reader_service import EventAuthorizationError


_TOKEN = "operator-secret-value"
_AUTH_HEADERS = {"Authorization": f"Bearer {_TOKEN}"}


@dataclass
class _FakeEventOperatorService:
    failure: Exception | None = None
    calls: list[tuple[str, dict[str, Any]]] = field(default_factory=list)

    def _result(self, operation: str, **arguments: Any) -> dict[str, Any]:
        self.calls.append((operation, arguments))
        if self.failure is not None:
            raise self.failure
        return {"operation": operation, "arguments": arguments}

    def list_quarantine(self, **arguments: Any) -> dict[str, Any]:
        return self._result("list_quarantine", **arguments)

    def get_quarantine(self, quarantine_id: str) -> dict[str, Any]:
        return self._result("get_quarantine", quarantine_id=quarantine_id)

    def list_replay_reports(self, **arguments: Any) -> dict[str, Any]:
        return self._result("list_replay_reports", **arguments)

    def get_replay_report(self, replay_id: str) -> dict[str, Any]:
        return self._result("get_replay_report", replay_id=replay_id)

    def list_dead_letters(self, **arguments: Any) -> dict[str, Any]:
        return self._result("list_dead_letters", **arguments)

    def get_dead_letter(self, dead_letter_id: str) -> dict[str, Any]:
        return self._result("get_dead_letter", dead_letter_id=dead_letter_id)

    def resolve_dead_letter(
        self,
        dead_letter_id: str,
        *,
        operator_reason: str,
    ) -> dict[str, Any]:
        return self._result(
            "resolve_dead_letter",
            dead_letter_id=dead_letter_id,
            operator_reason=operator_reason,
        )

    def requeue_dead_letter(self, dead_letter_id: str, **arguments: Any) -> dict[str, Any]:
        return self._result(
            "requeue_dead_letter",
            dead_letter_id=dead_letter_id,
            **arguments,
        )

    def get_consumer_status(self, **arguments: Any) -> dict[str, Any]:
        return self._result("get_consumer_status", **arguments)

    def get_projection_status(self, run_id: str) -> dict[str, Any]:
        return self._result("get_projection_status", run_id=run_id)


@dataclass
class _CapturingFactory:
    service: _FakeEventOperatorService
    actors: list[ActorContext] = field(default_factory=list)

    def __call__(self, actor: ActorContext) -> _FakeEventOperatorService:
        self.actors.append(actor)
        return self.service


def _client(
    service: _FakeEventOperatorService | None = None,
    *,
    api_keys: dict[str, list[str] | str] | None = None,
) -> tuple[TestClient, _FakeEventOperatorService, _CapturingFactory]:
    fake = service or _FakeEventOperatorService()
    factory = _CapturingFactory(fake)
    app = create_app(
        api_keys=api_keys or {_TOKEN: ["operator"]},
        event_operator_service_factory=factory,
        audit_emitter_factory=None,
    )
    return TestClient(app), fake, factory


def test_event_operator_list_routes_forward_only_explicit_filters() -> None:
    client, service, _ = _client()

    quarantine = client.get(
        "/api/v1/events/quarantine",
        params={
            "reason": "unknown_schema",
            "disposition": "pending",
            "cursor": "q-cursor",
            "limit": 25,
        },
        headers=_AUTH_HEADERS,
    )
    replay = client.get(
        "/api/v1/events/replay-reports",
        params={
            "source_stream_id": "run:run-1",
            "mode": "verify_history",
            "status": "completed",
            "cursor": "r-cursor",
            "limit": 30,
        },
        headers=_AUTH_HEADERS,
    )
    dead_letters = client.get(
        "/api/v1/events/dead-letters",
        params={
            "subscription_id": "report-indexer",
            "subscription_version": 2,
            "disposition": "pending",
            "cursor": "d-cursor",
            "limit": 40,
        },
        headers=_AUTH_HEADERS,
    )

    assert [response.status_code for response in (quarantine, replay, dead_letters)] == [
        200,
        200,
        200,
    ]
    assert service.calls == [
        (
            "list_quarantine",
            {
                "reason": "unknown_schema",
                "disposition": "pending",
                "cursor": "q-cursor",
                "limit": 25,
            },
        ),
        (
            "list_replay_reports",
            {
                "source_stream_id": "run:run-1",
                "mode": "verify_history",
                "status": "completed",
                "cursor": "r-cursor",
                "limit": 30,
            },
        ),
        (
            "list_dead_letters",
            {
                "subscription_id": "report-indexer",
                "subscription_version": 2,
                "disposition": "pending",
                "cursor": "d-cursor",
                "limit": 40,
            },
        ),
    ]


@pytest.mark.parametrize(
    ("path", "expected_call"),
    [
        (
            "/api/v1/events/quarantine/quarantine-1",
            ("get_quarantine", {"quarantine_id": "quarantine-1"}),
        ),
        (
            "/api/v1/events/replay-reports/replay-1",
            ("get_replay_report", {"replay_id": "replay-1"}),
        ),
        (
            "/api/v1/events/dead-letters/dead-1",
            ("get_dead_letter", {"dead_letter_id": "dead-1"}),
        ),
        (
            "/api/v1/events/consumers/report-indexer/versions/2/status"
            "?stream_id=run%3Arun-1",
            (
                "get_consumer_status",
                {
                    "subscription_id": "report-indexer",
                    "subscription_version": 2,
                    "stream_id": "run:run-1",
                },
            ),
        ),
        (
            "/api/v1/events/projections/runs/run-1/status",
            ("get_projection_status", {"run_id": "run-1"}),
        ),
    ],
)
def test_event_operator_detail_and_status_routes(
    path: str,
    expected_call: tuple[str, dict[str, Any]],
) -> None:
    client, service, _ = _client()

    response = client.get(path, headers=_AUTH_HEADERS)

    assert response.status_code == 200
    assert response.json()["data"]["operation"] == expected_call[0]
    assert service.calls == [expected_call]


def test_dead_letter_mutations_derive_operator_and_idempotency_evidence_server_side() -> None:
    client, service, _ = _client()

    resolved = client.post(
        "/api/v1/events/dead-letters/dead-1/resolve",
        json={"operator_reason": "reviewed and closed", "confirm": True},
        headers=_AUTH_HEADERS,
    )
    requeued = client.post(
        "/api/v1/events/dead-letters/dead-2/requeue",
        json={
            "subscription_id": "report-indexer",
            "subscription_version": 3,
            "operator_reason": "consumer repair deployed",
            "confirm": True,
        },
        headers=_AUTH_HEADERS,
    )

    assert resolved.status_code == 200
    assert requeued.status_code == 200
    assert service.calls == [
        (
            "resolve_dead_letter",
            {
                "dead_letter_id": "dead-1",
                "operator_reason": "reviewed and closed",
            },
        ),
        (
            "requeue_dead_letter",
            {
                "dead_letter_id": "dead-2",
                "subscription_id": "report-indexer",
                "subscription_version": 3,
                "operator_reason": "consumer repair deployed",
                "idempotency_acknowledged": True,
            },
        ),
    ]


@pytest.mark.parametrize(
    "forbidden_field",
    [
        "tenant_id",
        "operator_id",
        "requested_at",
        "idempotency_ready",
        "idempotency_acknowledged",
    ],
)
def test_dead_letter_mutation_body_rejects_caller_owned_security_fields(
    forbidden_field: str,
) -> None:
    client, service, factory = _client()
    body: dict[str, Any] = {
        "operator_reason": "repair",
        "confirm": True,
        forbidden_field: "forged",
    }

    response = client.post(
        "/api/v1/events/dead-letters/dead-1/resolve",
        json=body,
        headers=_AUTH_HEADERS,
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_request"
    assert service.calls == []
    assert factory.actors == []


@pytest.mark.parametrize("confirm", [False, 1, "true"])
def test_dead_letter_mutation_requires_explicit_boolean_confirmation(confirm: Any) -> None:
    client, service, _ = _client()

    response = client.post(
        "/api/v1/events/dead-letters/dead-1/resolve",
        json={"operator_reason": "repair", "confirm": confirm},
        headers=_AUTH_HEADERS,
    )

    assert response.status_code == 422
    assert service.calls == []


@pytest.mark.parametrize(("reason_length", "status_code"), [(512, 200), (513, 422)])
def test_dead_letter_mutation_enforces_shared_reason_limit(
    reason_length: int,
    status_code: int,
) -> None:
    client, service, _ = _client()

    response = client.post(
        "/api/v1/events/dead-letters/dead-1/resolve",
        json={"operator_reason": "r" * reason_length, "confirm": True},
        headers=_AUTH_HEADERS,
    )

    assert response.status_code == status_code
    assert len(service.calls) == (1 if status_code == 200 else 0)


def test_event_operator_query_rejects_tenant_and_operator_override() -> None:
    client, service, _ = _client()

    response = client.get(
        "/api/v1/events/quarantine",
        params={"tenant_id": "other-tenant", "operator_id": "forged"},
        headers=_AUTH_HEADERS,
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_event_operator_request"
    assert service.calls == []


def test_event_operator_requires_request_state_actor_without_header_fallback() -> None:
    service = _FakeEventOperatorService()
    factory = _CapturingFactory(service)
    client = TestClient(
        create_app(
            event_operator_service_factory=factory,
            audit_emitter_factory=None,
        )
    )

    response = client.get(
        "/api/v1/events/quarantine",
        headers={
            "X-News-Actor": "forged-operator",
            "X-News-Roles": "operator",
            "X-News-Permissions": "events:read,events:operate",
        },
    )

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthorized"
    assert factory.actors == []


def test_api_key_actor_identity_uses_server_derived_fingerprint() -> None:
    client, _, factory = _client()
    spoofed_headers = {
        **_AUTH_HEADERS,
        "X-API-Client-ID": "forged-client",
        "X-News-Actor": "forged-operator",
    }

    response = client.get("/api/v1/events/quarantine", headers=spoofed_headers)

    expected = hashlib.sha256(_TOKEN.encode("utf-8")).hexdigest()
    assert response.status_code == 200
    assert factory.actors[0].actor_id == f"api-key:{expected}"
    assert "forged" not in factory.actors[0].actor_id
    assert _TOKEN[:6] not in factory.actors[0].actor_id


def test_create_app_reuses_event_operator_factory_for_default_mcp_service() -> None:
    client, service, factory = _client()

    rest_response = client.get("/api/v1/events/quarantine", headers=_AUTH_HEADERS)
    mcp_response = client.post(
        "/api/v1/mcp/tools/news.event.quarantine.list/call",
        json={"arguments": {}},
        headers=_AUTH_HEADERS,
    )

    assert rest_response.status_code == 200
    assert mcp_response.status_code == 200
    assert mcp_response.json()["data"]["success"] is True
    assert [call[0] for call in service.calls] == [
        "list_quarantine",
        "list_quarantine",
    ]
    assert len(factory.actors) == 2
    assert factory.actors[0].actor_id == factory.actors[1].actor_id


def test_http_mcp_event_surfaces_do_not_inherit_deployment_actor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("NEWS_API_KEYS", raising=False)
    monkeypatch.setenv("NEWS_EVENT_OPERATOR_PRINCIPAL_ID", "deployment-operator")
    monkeypatch.setenv("NEWS_EVENT_OPERATOR_ROLE", "operator")
    monkeypatch.setenv("NEWS_TENANT_ID", "tenant-a")
    service = _FakeEventOperatorService()
    factory = _CapturingFactory(service)
    client = TestClient(
        create_app(
            event_operator_service_factory=factory,
            audit_emitter_factory=None,
        )
    )

    responses = [
        client.post(
            "/api/v1/mcp/tools/news.event.dead_letters.resolve/call",
            json={
                "arguments": {
                    "dead_letter_id": "dead-1",
                    "operator_reason": "repair",
                    "confirm": True,
                }
            },
        ),
        *[
            client.post(
                "/api/v1/mcp/resources/read",
                json={"uri": uri},
            )
            for uri in (
                "news://events/quarantine",
                "NEWS://events/quarantine",
                "News://events/quarantine",
            )
        ],
    ]

    assert [response.status_code for response in responses] == [401] * 4
    assert [response.json()["error"]["code"] for response in responses] == [
        "unauthorized"
    ] * 4
    assert all(response.headers["WWW-Authenticate"] == "Bearer" for response in responses)
    assert service.calls == []
    assert factory.actors == []


@pytest.mark.parametrize("role", ["viewer", "developer", "read-only", "mcp_client"])
def test_untrusted_roles_cannot_read_event_operator_routes(role: str) -> None:
    client, service, factory = _client(api_keys={_TOKEN: [role]})

    response = client.get("/api/v1/events/quarantine", headers=_AUTH_HEADERS)

    assert response.status_code == 403
    assert response.json()["error"]["details"]["required_permission"] == "events:read"
    assert service.calls == []
    assert factory.actors == []


@pytest.mark.parametrize("role", ["admin", "operator", "service"])
def test_trusted_roles_can_operate_event_routes(role: str) -> None:
    client, service, _ = _client(api_keys={_TOKEN: [role]})

    read_response = client.get("/api/v1/events/quarantine", headers=_AUTH_HEADERS)
    write_response = client.post(
        "/api/v1/events/dead-letters/dead-1/resolve",
        json={"operator_reason": "approved", "confirm": True},
        headers=_AUTH_HEADERS,
    )

    assert read_response.status_code == 200
    assert write_response.status_code == 200
    assert [call[0] for call in service.calls] == [
        "list_quarantine",
        "resolve_dead_letter",
    ]


@pytest.mark.parametrize(
    ("failure", "status_code", "error_code"),
    [
        (EventAuthorizationError("denied"), 403, "forbidden"),
        (
            EventOperationNotFoundError("hidden target"),
            404,
            "event_operator_resource_not_found",
        ),
        (
            EventOperationCapabilityUnavailableError("runtime missing"),
            503,
            "event_operator_capability_unavailable",
        ),
        (EventStoreUnavailableError("offline"), 503, "event_store_unavailable"),
        (
            EventContractError("cross-tenant record"),
            409,
            "event_operator_contract_conflict",
        ),
        (ValueError("limit is invalid"), 400, "invalid_event_operator_request"),
    ],
)
def test_event_operator_errors_have_stable_http_mapping(
    failure: Exception,
    status_code: int,
    error_code: str,
) -> None:
    client, _, _ = _client(_FakeEventOperatorService(failure=failure))

    response = client.get("/api/v1/events/quarantine", headers=_AUTH_HEADERS)

    assert response.status_code == status_code
    assert response.json()["error"]["code"] == error_code
    assert "hidden target" not in response.text
    assert "cross-tenant record" not in response.text


def test_event_operator_openapi_exposes_only_public_mutation_fields() -> None:
    client, _, _ = _client()

    schema = client.app.openapi()
    paths = schema["paths"]
    assert "/api/v1/events/quarantine" in paths
    assert "/api/v1/events/replay-reports" in paths
    assert "/api/v1/events/dead-letters/{dead_letter_id}/resolve" in paths
    assert "/api/v1/events/dead-letters/{dead_letter_id}/requeue" in paths
    assert (
        "/api/v1/events/consumers/{subscription_id}/versions/"
        "{subscription_version}/status"
    ) in paths
    assert "/api/v1/events/projections/runs/{run_id}/status" in paths

    components = schema["components"]["schemas"]
    resolve_schema = components["DeadLetterResolveRequest"]
    requeue_schema = components["DeadLetterRequeueRequest"]
    assert set(resolve_schema["properties"]) == {"operator_reason", "confirm"}
    assert set(requeue_schema["properties"]) == {
        "subscription_id",
        "subscription_version",
        "operator_reason",
        "confirm",
    }
    assert resolve_schema["additionalProperties"] is False
    assert requeue_schema["additionalProperties"] is False
    assert resolve_schema["properties"]["operator_reason"]["maxLength"] == 512
    assert requeue_schema["properties"]["operator_reason"]["maxLength"] == 512
