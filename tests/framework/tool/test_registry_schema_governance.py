from __future__ import annotations

import pytest

from framework.tool import (
    MappingSecretProvider,
    ToolDefinition,
    ToolJsonSchemaBuilder,
    ToolParameter,
    ToolRegistry,
    ToolResolver,
    register_control_tools,
)


def test_registry_resolver_and_schema_builder() -> None:
    registry = ToolRegistry()
    definition = ToolDefinition(name="sample.add")
    registry.register(definition, lambda args: args)

    schema = ToolJsonSchemaBuilder().build(
        [ToolParameter(name="value", type="integer", required=True)]
    )

    assert ToolResolver().resolve("sample.add", registry).definition == definition
    assert schema["required"] == ["value"]
    assert schema["properties"]["value"]["type"] == "integer"


def test_secret_provider_and_control_tool_success() -> None:
    assert MappingSecretProvider({"TOKEN": "secret"}).get_secret("TOKEN") == "secret"

    registry = ToolRegistry()
    register_control_tools(registry, approval_store=_ApprovalStore())
    result = registry.get("control.request_human_review").executor(
        {
            "requested_action": "review",
            "reason": "needs review",
            "payload": {"record_id": "r1"},
        }
    )

    assert result["control_action"] == "request_human_review"


def test_control_tool_rejects_sensitive_payload_keys() -> None:
    registry = ToolRegistry()
    register_control_tools(registry, approval_store=_ApprovalStore())

    with pytest.raises(ValueError, match="payload key is not allowed"):
        registry.get("control.request_human_review").executor(
            {
                "requested_action": "review",
                "reason": "needs review",
                "payload": {"api_key": "hidden"},
            }
        )


class _ApprovalStore:
    def upsert_approval(self, request):
        return request
