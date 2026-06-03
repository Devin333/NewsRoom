from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from framework import RunResult
from infrastructure.storage.repository import (
    RunPersistenceInput,
    run_persistence_input_from_output,
)
from interfaces.services.daily_output_projection import (
    project_daily_run_output_for_persistence as project_daily_output_for_persistence_view,
)


def project_daily_run_output_for_persistence(result: RunResult) -> dict[str, Any]:
    output = result.output
    if not isinstance(output, Mapping):
        return {}
    return project_daily_output_for_persistence_view(output)


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
