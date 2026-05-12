from __future__ import annotations

from typing import Any

from core.framework.tools.models import ToolDefinition
from core.framework.tools.registry import ToolRegistry


def register_control_tools(registry: ToolRegistry) -> None:
    registry.register(
        ToolDefinition(
            name="control.set_output",
            description="Submit a final output candidate for the current agent loop.",
            input_schema={
                "required": ["output"],
                "properties": {
                    "output": {"type": "object"},
                    "reason": {"type": "string"},
                },
                "additionalProperties": False,
            },
            side_effect="none",
            concurrency_safe=False,
        ),
        _set_output,
    )
    registry.register(
        ToolDefinition(
            name="control.report_progress",
            description="Report structured progress for the current agent loop.",
            input_schema={
                "required": ["message"],
                "properties": {
                    "message": {"type": "string"},
                    "percent": {"type": "number"},
                    "metadata": {"type": "object"},
                },
                "additionalProperties": False,
            },
            side_effect="none",
            concurrency_safe=True,
        ),
        _report_progress,
    )


def _set_output(args: dict[str, Any]) -> dict[str, Any]:
    output = args["output"]
    if not isinstance(output, dict):
        raise ValueError("output must be an object")
    reason = args.get("reason")
    return {
        "control_action": "set_output",
        "output": dict(output),
        "reason": str(reason) if reason is not None else None,
    }


def _report_progress(args: dict[str, Any]) -> dict[str, Any]:
    percent = args.get("percent")
    if percent is not None:
        percent = float(percent)
        if percent < 0.0 or percent > 100.0:
            raise ValueError("percent must be between 0 and 100")
    metadata = args.get("metadata") or {}
    if not isinstance(metadata, dict):
        raise ValueError("metadata must be an object")
    return {
        "control_action": "report_progress",
        "message": str(args["message"]),
        "percent": percent,
        "metadata": dict(metadata),
    }
