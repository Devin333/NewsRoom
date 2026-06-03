from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from business.boards.cross_board.workflows.daily_intelligence.output_projection import (
    project_daily_output_for_persistence,
)
from framework import RunResult
from infrastructure.storage.repository import (
    RunPersistenceInput,
    run_persistence_input_from_output,
)


def project_daily_run_output_for_persistence(result: RunResult) -> dict[str, Any]:
    output = result.output
    if not isinstance(output, Mapping):
        return {}
    return project_daily_output_for_persistence(output)


def daily_run_persistence_input_from_result(
    result: RunResult,
    *,
    profile: str,
) -> RunPersistenceInput:
    return run_persistence_input_from_output(
        result,
        project_daily_run_output_for_persistence(result),
        profile=profile,
    )


__all__ = [
    "daily_run_persistence_input_from_result",
    "project_daily_run_output_for_persistence",
]
