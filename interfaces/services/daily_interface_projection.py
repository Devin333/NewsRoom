from __future__ import annotations

from typing import Any

from business.boards.cross_board.profiles import is_daily_workflow_id
from business.boards.cross_board.workflows.daily_intelligence.output_projection import (
    apply_daily_public_output_aliases,
    daily_output_value,
)


def project_run_output_for_interface(payload: dict[str, Any]) -> Any:
    output = payload.get("output")
    if not isinstance(output, dict):
        return output
    if not is_daily_workflow_id(str(payload.get("workflow_id") or "")):
        return output
    return apply_daily_public_output_aliases(dict(output))


def project_daily_agent_loop_metrics_for_interface(output: Any) -> dict[str, Any]:
    if not isinstance(output, dict):
        return {}
    metrics = daily_output_value(output, "agent_loop_metrics", default={})
    return dict(metrics) if isinstance(metrics, dict) else {}


__all__ = [
    "project_daily_agent_loop_metrics_for_interface",
    "project_run_output_for_interface",
]
