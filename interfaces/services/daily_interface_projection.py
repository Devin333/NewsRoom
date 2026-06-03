from __future__ import annotations

from typing import Any

from business.boards.cross_board.profiles import is_daily_workflow_id
from business.boards.cross_board.workflows.daily_intelligence.output_projection import (
    apply_daily_public_output_aliases,
)


def project_run_output_for_interface(payload: dict[str, Any]) -> Any:
    output = payload.get("output")
    if not isinstance(output, dict):
        return output
    if not is_daily_workflow_id(str(payload.get("workflow_id") or "")):
        return output
    return apply_daily_public_output_aliases(dict(output))


__all__ = ["project_run_output_for_interface"]
