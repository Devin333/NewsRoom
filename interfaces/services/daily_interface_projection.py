from __future__ import annotations

from typing import Any

from business.boards.cross_board.profiles import is_daily_workflow_id
from interfaces.services.daily_output_projection import (
    apply_daily_run_public_output_aliases,
    project_daily_run_agent_loop_metrics,
)


def project_run_output_for_interface(payload: dict[str, Any]) -> Any:
    output = payload.get("output")
    if not isinstance(output, dict):
        return output
    if not is_daily_workflow_id(str(payload.get("workflow_id") or "")):
        return output
    return apply_daily_run_public_output_aliases(dict(output))


def project_daily_agent_loop_metrics_for_interface(output: Any) -> dict[str, Any]:
    return project_daily_run_agent_loop_metrics(output)


__all__ = [
    "project_daily_agent_loop_metrics_for_interface",
    "project_run_output_for_interface",
]
