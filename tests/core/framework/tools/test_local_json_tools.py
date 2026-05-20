import json

from framework.tool import (
    ToolCall,
    ToolExecutor,
    ToolPolicy,
    ToolRegistry,
    ToolStatus,
)
from infrastructure.tools import (
    register_local_json_tools,
)


def test_local_json_save_tool_writes_scoped_json_record(tmp_path) -> None:
    registry = ToolRegistry()
    register_local_json_tools(registry, root=tmp_path)
    executor = ToolExecutor(registry)

    observation = executor.execute(
        ToolCall(
            tool_name="local_json.save",
            arguments={
                "collection": "tool_records",
                "record_id": "record-1",
                "value": {"status": "ok"},
                "metadata": {"run_id": "run-1"},
            },
        ),
        ToolPolicy(
            allowed_tools=["local_json.save"],
            require_approval_for_side_effects=False,
        ),
    )

    record_path = tmp_path / "tool_records" / "record-1.json"
    record = json.loads(record_path.read_text(encoding="utf-8"))

    assert observation.status == ToolStatus.SUCCEEDED
    assert observation.result.output["saved"] is True
    assert observation.result.output["relative_path"] == "tool_records/record-1.json"
    assert "value" not in observation.result.output
    assert record["value"] == {"status": "ok"}
    assert record["metadata"] == {"run_id": "run-1"}


def test_local_json_save_tool_requires_approval_by_default(tmp_path) -> None:
    registry = ToolRegistry()
    register_local_json_tools(registry, root=tmp_path)
    executor = ToolExecutor(registry)

    observation = executor.execute(
        ToolCall(
            tool_name="local_json.save",
            arguments={
                "collection": "tool_records",
                "record_id": "record-1",
                "value": {"status": "ok"},
            },
        ),
        ToolPolicy(allowed_tools=["local_json.save"]),
    )

    assert observation.status == ToolStatus.APPROVAL_REQUIRED
    assert not (tmp_path / "tool_records" / "record-1.json").exists()


def test_local_json_save_tool_rejects_unsafe_record_names(tmp_path) -> None:
    registry = ToolRegistry()
    register_local_json_tools(registry, root=tmp_path)
    executor = ToolExecutor(registry)

    observation = executor.execute(
        ToolCall(
            tool_name="local_json.save",
            arguments={
                "collection": "../outside",
                "record_id": "record-1",
                "value": {"status": "ok"},
            },
        ),
        ToolPolicy(
            allowed_tools=["local_json.save"],
            require_approval_for_side_effects=False,
        ),
    )

    assert observation.status == ToolStatus.FAILED
    assert "safe record name" in (observation.result.error_message or "")
    assert not (tmp_path.parent / "outside").exists()
