import json

from core.framework.artifacts import ArtifactManager
from core.framework.tools import (
    REDACTED_VALUE,
    ToolCall,
    ToolDefinition,
    ToolExecutor,
    ToolPolicy,
    ToolRegistry,
    ToolResult,
    ToolStatus,
)
from core.framework.tools.redaction import redact_sensitive_values


def _registry() -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(
        ToolDefinition(
            name="memory.search",
            description="Search local memory",
            input_schema={"required": ["query"]},
        ),
        lambda args: {"matches": [{"title": args["query"], "score": 1.0}]},
    )
    return registry


def test_tool_executor_runs_allowed_tool_and_returns_observation() -> None:
    executor = ToolExecutor(_registry())

    observation = executor.execute(
        ToolCall(
            tool_name="memory.search",
            arguments={"query": "chip exports"},
            requested_by_agent_id="analyst",
            call_id="call-1",
        ),
        ToolPolicy(allowed_tools=["memory.search"]),
    )

    assert observation.status == ToolStatus.SUCCEEDED
    assert observation.call.call_id == "call-1"
    assert observation.result.output["matches"][0]["title"] == "chip exports"
    assert observation.elapsed_ms >= 0


def test_tool_executor_blocks_disallowed_tool() -> None:
    executor = ToolExecutor(_registry())

    observation = executor.execute(
        ToolCall(
            tool_name="memory.search",
            arguments={"query": "chip exports"},
            requested_by_agent_id="writer",
        ),
        ToolPolicy(allowed_tools=[]),
    )

    assert observation.status == ToolStatus.BLOCKED
    assert observation.result.error_type == "ToolPermissionError"


def test_tool_executor_fails_missing_required_arguments() -> None:
    executor = ToolExecutor(_registry())

    observation = executor.execute(
        ToolCall(tool_name="memory.search", arguments={}, requested_by_agent_id="analyst"),
        ToolPolicy(allowed_tools=["memory.search"]),
    )

    assert observation.status == ToolStatus.FAILED
    assert observation.result.error_type == "ToolRuntimeError"
    assert "missing required arguments" in (observation.result.error_message or "")


def test_tool_executor_redacts_sensitive_output_and_serialized_arguments() -> None:
    registry = ToolRegistry()
    registry.register(
        ToolDefinition(
            name="http.request",
            description="Fetch a protected resource",
            input_schema={"required": ["url"]},
        ),
        lambda args: {
            "token": "hidden-token",
            "nested": {"api_key": "hidden-key", "safe": "visible"},
            "headers": ["Bearer abcdef1234567890"],
            "url": args["url"],
        },
    )
    executor = ToolExecutor(registry)

    observation = executor.execute(
        ToolCall(
            tool_name="http.request",
            arguments={"url": "https://example.com", "authorization": "Bearer input-secret"},
            requested_by_agent_id="analyst",
            call_id="call-1",
        ),
        ToolPolicy(allowed_tools=["http.request"]),
    )

    payload = observation.to_dict()

    assert observation.status == ToolStatus.SUCCEEDED
    assert observation.result.output["token"] == REDACTED_VALUE
    assert observation.result.output["nested"]["api_key"] == REDACTED_VALUE
    assert observation.result.output["nested"]["safe"] == "visible"
    assert payload["call"]["arguments"]["authorization"] == REDACTED_VALUE
    assert payload["result"]["redacted"] is True
    assert "hidden-token" not in str(payload)
    assert "hidden-key" not in str(payload)
    assert "input-secret" not in str(payload)


def test_tool_result_to_dict_redacts_secret_like_strings() -> None:
    fake_secret = "sk" + "-abcdef1234567890"
    result = ToolResult(
        status=ToolStatus.SUCCEEDED,
        output={"message": f"provider returned {fake_secret}"},
    )

    payload = result.to_dict()

    assert payload["output"]["message"] == f"provider returned {REDACTED_VALUE}"


def test_tool_redactor_handles_nested_lists() -> None:
    payload = redact_sensitive_values(
        [{"password": "hidden"}, {"message": "Bearer abcdef1234567890"}]
    )

    assert payload == [
        {"password": REDACTED_VALUE},
        {"message": REDACTED_VALUE},
    ]


def test_tool_executor_spills_large_redacted_result_to_artifact(tmp_path) -> None:
    registry = ToolRegistry()
    registry.register(
        ToolDefinition(name="memory.large", input_schema={"required": ["query"]}),
        lambda args: {
            "items": [{"title": args["query"], "body": "x" * 80}],
            "token": "hidden-token",
        },
    )
    artifact_manager = ArtifactManager(tmp_path)
    artifact_manager.start_run("run-1")
    executor = ToolExecutor(
        registry,
        artifact_manager=artifact_manager,
        run_id="run-1",
    )

    observation = executor.execute(
        ToolCall(
            tool_name="memory.large",
            arguments={"query": "chips"},
            requested_by_agent_id="analyst",
            call_id="call-large",
        ),
        ToolPolicy(allowed_tools=["memory.large"], max_result_chars_inline=20),
    )

    payload = observation.to_dict()
    artifact_ref = payload["result"]["artifact_refs"][0]
    artifact_path = tmp_path / "run-1" / artifact_ref["relative_path"]
    artifact_payload = json.loads(artifact_path.read_text(encoding="utf-8"))

    assert observation.status == ToolStatus.SUCCEEDED
    assert observation.result.output is None
    assert observation.result.output_bytes is not None
    assert observation.result.output_bytes > 20
    assert "Tool result spilled" in (observation.result.output_summary or "")
    assert artifact_ref["artifact_id"] == "tool_result:call-large"
    assert artifact_ref["content_type"] == "application/json"
    assert artifact_path.exists()
    assert artifact_payload["call"]["call_id"] == "call-large"
    assert artifact_payload["output"]["token"] == REDACTED_VALUE
    assert "hidden-token" not in artifact_path.read_text(encoding="utf-8")


def test_tool_executor_keeps_large_result_inline_without_artifact_context() -> None:
    registry = ToolRegistry()
    registry.register(
        ToolDefinition(name="memory.large", input_schema={"required": ["query"]}),
        lambda args: {"items": ["x" * 80], "token": "hidden-token"},
    )
    executor = ToolExecutor(registry)

    observation = executor.execute(
        ToolCall(tool_name="memory.large", arguments={"query": "chips"}),
        ToolPolicy(allowed_tools=["memory.large"], max_result_chars_inline=20),
    )

    assert observation.status == ToolStatus.SUCCEEDED
    assert observation.result.output == {"items": ["x" * 80], "token": REDACTED_VALUE}
    assert observation.result.artifact_refs == []
