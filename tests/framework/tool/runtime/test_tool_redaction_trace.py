from __future__ import annotations

import json
from pathlib import Path

from framework.tool import ToolCall, ToolDefinition, ToolExecutor, ToolPolicy, ToolRegistry


def test_tool_redaction_trace_does_not_expose_secret_like_output() -> None:
    registry = ToolRegistry()
    registry.register(
        ToolDefinition(name="sample.secret", input_schema={}),
        lambda args: {"token": "sk-1234567890abcdef"},
    )

    result = ToolExecutor(registry).execute(
        ToolCall(tool_name="sample.secret", call_id="secret"),
        ToolPolicy(allowed_tools=["sample.secret"]),
    ).result
    payload = result.to_dict()
    encoded = json.dumps(payload, sort_keys=True)

    assert "sk-1234567890abcdef" not in encoded
    assert payload["redacted_output"]["token"] == "[redacted]"
    assert "tool.redaction" in {
        check["check_id"] for check in payload["policy_trace"]["checks"]
    }


def test_tool_artifact_spill_records_refs_and_policy_trace(tmp_path) -> None:
    registry = ToolRegistry()
    registry.register(
        ToolDefinition(name="sample.large", input_schema={}),
        lambda args: {"message": "x" * 100},
    )
    manager = _TinyArtifactManager(tmp_path)

    result = ToolExecutor(
        registry,
        artifact_manager=manager,
        run_id="run-1",
    ).execute(
        ToolCall(tool_name="sample.large", call_id="spill"),
        ToolPolicy(
            allowed_tools=["sample.large"],
            max_result_chars_inline=4,
            spill_large_results_to_artifact=True,
        ),
    ).result
    payload = result.to_dict()

    assert payload["output"] is None
    assert payload["artifact_refs"]
    assert payload["policy_trace"]["checks"][-1]["check_id"] == "tool.artifact_spill"
    assert payload["policy_trace"]["checks"][-1]["passed"] is True


class _TinyArtifactManager:
    def __init__(self, root: Path) -> None:
        self.root = root

    def write_json(self, run_id: str, relative_path: str, payload: dict) -> Path:
        path = self.root / run_id / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload), encoding="utf-8")
        return path
