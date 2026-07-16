from __future__ import annotations

from interfaces.models.actor import ActorContext
from interfaces.services.mcp_service import (
    EVENT_DEAD_LETTERS_RESOURCE_URI,
    MCPApplicationService,
    resource_required_permission,
    tool_required_permission,
)


class _EventOperatorService:
    def __init__(self) -> None:
        self.calls: list[tuple[str, object]] = []

    def list_quarantine(self, **kwargs):
        self.calls.append(("list_quarantine", kwargs))
        return {
            "availability": "available",
            "tenant_id": "tenant-a",
            "items": [],
            "next_cursor": None,
        }

    def get_quarantine(self, quarantine_id):
        self.calls.append(("get_quarantine", quarantine_id))
        return {"availability": "available", "found": False, "item": None}

    def list_replay_reports(self, **kwargs):
        self.calls.append(("list_replay_reports", kwargs))
        return {"availability": "available", "items": [], "next_cursor": None}

    def get_replay_report(self, replay_id):
        self.calls.append(("get_replay_report", replay_id))
        return {"availability": "available", "found": False, "item": None}

    def list_dead_letters(self, **kwargs):
        self.calls.append(("list_dead_letters", kwargs))
        return {"availability": "available", "items": [], "next_cursor": None}

    def get_dead_letter(self, dead_letter_id):
        self.calls.append(("get_dead_letter", dead_letter_id))
        return {"availability": "available", "found": False, "item": None}

    def resolve_dead_letter(self, dead_letter_id, *, operator_reason):
        self.calls.append(
            (
                "resolve_dead_letter",
                {"dead_letter_id": dead_letter_id, "operator_reason": operator_reason},
            )
        )
        return {"dead_letter_id": dead_letter_id, "disposition": "resolved"}

    def requeue_dead_letter(self, dead_letter_id, **kwargs):
        self.calls.append(
            ("requeue_dead_letter", {"dead_letter_id": dead_letter_id, **kwargs})
        )
        return {"delivery_id": "delivery-2", "state": "pending"}

    def get_consumer_status(self, subscription_id, **kwargs):
        self.calls.append(
            ("get_consumer_status", {"subscription_id": subscription_id, **kwargs})
        )
        return {"availability": "available", "found": True, "lag": 0}

    def get_projection_status(self, run_id):
        self.calls.append(("get_projection_status", run_id))
        return {"availability": "available", "run_id": run_id, "status": "current"}


def _actor() -> ActorContext:
    return ActorContext(
        actor_id="operator-1",
        actor_type="service",
        roles=["operator"],
        request_id="request-1",
    )


def test_event_operator_tools_bind_authenticated_actor_and_keep_scope_out_of_args() -> None:
    operator = _EventOperatorService()
    actors = []
    service = MCPApplicationService(
        event_operator_service_factory=lambda actor: (
            actors.append(actor) or operator
        ),
        operator_actor=_actor(),
    )

    listed = service.call_tool(
        "news.event.dead_letters.list",
        {"subscription_id": "subscription-1", "subscription_version": 1},
    )
    resolved = service.call_tool(
        "news.event.dead_letters.resolve",
        {
            "dead_letter_id": "dead-letter-1",
            "operator_reason": "verified terminal resolution",
            "confirm": True,
        },
    )

    assert listed.success is True
    assert resolved.success is True
    assert actors == [_actor(), _actor()]
    assert operator.calls[-1] == (
        "resolve_dead_letter",
        {
            "dead_letter_id": "dead-letter-1",
            "operator_reason": "verified terminal resolution",
        },
    )


def test_event_operator_mutation_requires_boolean_confirmation() -> None:
    operator = _EventOperatorService()
    service = MCPApplicationService(
        event_operator_service_factory=lambda actor: operator,
        operator_actor=_actor(),
    )

    result = service.call_tool(
        "news.event.dead_letters.resolve",
        {
            "dead_letter_id": "dead-letter-1",
            "operator_reason": "resolve",
            "confirm": "true",
        },
    )

    assert result.success is False
    assert operator.calls == []


def test_event_operator_tools_reject_caller_asserted_scope_and_time() -> None:
    operator = _EventOperatorService()
    service = MCPApplicationService(
        event_operator_service_factory=lambda actor: operator,
        operator_actor=_actor(),
    )

    for forbidden in ("tenant_id", "operator_id", "requested_at", "idempotency_ready"):
        result = service.call_tool(
            "news.event.dead_letters.requeue",
            {
                "dead_letter_id": "dead-letter-1",
                "subscription_id": "subscription-1",
                "subscription_version": 1,
                "operator_reason": "retry after repair",
                "confirm": True,
                forbidden: "forged",
            },
        )
        assert result.success is False

    assert operator.calls == []


def test_event_operator_resources_are_tenant_scoped_through_bound_service() -> None:
    operator = _EventOperatorService()
    service = MCPApplicationService(
        event_operator_service_factory=lambda actor: operator,
        operator_actor=_actor(),
    )

    result = service.read_resource(
        EVENT_DEAD_LETTERS_RESOURCE_URI
        + "?subscription_id=subscription-1&subscription_version=1"
    )

    assert result.success is True
    assert result.data == {
        "availability": "available",
        "items": [],
        "next_cursor": None,
    }
    assert operator.calls == [
        (
            "list_dead_letters",
            {
                "subscription_id": "subscription-1",
                "subscription_version": 1,
                "disposition": None,
                "cursor": None,
                "limit": 100,
            },
        )
    ]


def test_event_operator_catalog_declares_granular_permissions_and_closed_schemas() -> None:
    catalog = MCPApplicationService(operator_actor=_actor()).catalog()
    tools = {tool.name: tool for tool in catalog.tools}

    assert tool_required_permission("news.event.quarantine.list") == "events:read"
    assert tool_required_permission("news.event.dead_letters.resolve") == "events:operate"
    assert resource_required_permission(EVENT_DEAD_LETTERS_RESOURCE_URI) == "events:read"
    requeue_schema = tools["news.event.dead_letters.requeue"].input_schema
    assert requeue_schema["additionalProperties"] is False
    assert "tenant_id" not in requeue_schema["properties"]
    assert "operator_id" not in requeue_schema["properties"]
    assert "requested_at" not in requeue_schema["properties"]


def test_event_operator_mcp_fails_closed_without_authenticated_actor(monkeypatch) -> None:
    monkeypatch.delenv("NEWS_EVENT_OPERATOR_PRINCIPAL_ID", raising=False)
    monkeypatch.delenv("NEWS_TENANT_ID", raising=False)
    service = MCPApplicationService(
        event_operator_service_factory=lambda actor: (_ for _ in ()).throw(
            AssertionError("factory must not run")
        )
    )

    result = service.call_tool("news.event.quarantine.list", {})

    assert result.success is False
    assert result.data is None
