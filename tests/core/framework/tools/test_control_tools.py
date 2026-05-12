from core.framework.tools import (
    ToolCall,
    ToolExecutor,
    ToolPolicy,
    ToolRegistry,
    ToolStatus,
    register_control_tools,
)


def test_control_set_output_tool_returns_final_output_payload() -> None:
    registry = ToolRegistry()
    register_control_tools(registry)
    executor = ToolExecutor(registry)

    observation = executor.execute(
        ToolCall(
            tool_name="control.set_output",
            arguments={
                "output": {"analysis_result": {"summary": "ok"}},
                "reason": "complete",
            },
        ),
        ToolPolicy(allowed_tools=["control.set_output"]),
    )

    assert observation.status == ToolStatus.SUCCEEDED
    assert observation.result.output == {
        "control_action": "set_output",
        "output": {"analysis_result": {"summary": "ok"}},
        "reason": "complete",
    }


def test_control_report_progress_tool_returns_structured_progress() -> None:
    registry = ToolRegistry()
    register_control_tools(registry)
    executor = ToolExecutor(registry)

    observation = executor.execute(
        ToolCall(
            tool_name="control.report_progress",
            arguments={
                "message": "collected sources",
                "percent": 40,
                "metadata": {"source_count": 3},
            },
        ),
        ToolPolicy(allowed_tools=["control.report_progress"]),
    )

    assert observation.status == ToolStatus.SUCCEEDED
    assert observation.result.output == {
        "control_action": "report_progress",
        "message": "collected sources",
        "percent": 40.0,
        "metadata": {"source_count": 3},
    }


def test_control_report_progress_tool_rejects_invalid_percent() -> None:
    registry = ToolRegistry()
    register_control_tools(registry)
    executor = ToolExecutor(registry)

    observation = executor.execute(
        ToolCall(
            tool_name="control.report_progress",
            arguments={"message": "bad", "percent": 101},
        ),
        ToolPolicy(allowed_tools=["control.report_progress"]),
    )

    assert observation.status == ToolStatus.FAILED
    assert "percent" in (observation.result.error_message or "")
