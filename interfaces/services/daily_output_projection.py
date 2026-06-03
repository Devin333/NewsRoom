from __future__ import annotations

from typing import Any

from business.boards.cross_board.workflows.daily_intelligence.output_projection import (
    apply_daily_board_attachment_result,
    apply_daily_public_output_aliases,
    daily_output_value,
    project_daily_output_for_board_attachment,
    project_daily_output_for_memory_ingestion,
    project_daily_output_for_persistence,
    project_daily_output_for_run_inspection,
)


def project_daily_run_output_for_memory_ingestion(output: Any) -> dict[str, Any]:
    return project_daily_output_for_memory_ingestion(output)


def project_daily_run_output_for_persistence(output: Any) -> dict[str, Any]:
    return project_daily_output_for_persistence(output)


def project_daily_run_output_for_board_attachment(output: dict[str, Any]) -> dict[str, Any]:
    return project_daily_output_for_board_attachment(output)


def project_daily_run_output_for_run_inspection(output: dict[str, Any]) -> dict[str, Any]:
    return project_daily_output_for_run_inspection(output)


def apply_daily_run_board_attachment_result(
    output: dict[str, Any],
    board_output: dict[str, Any],
) -> dict[str, Any]:
    return apply_daily_board_attachment_result(output, board_output)


def apply_daily_run_public_output_aliases(output: dict[str, Any]) -> dict[str, Any]:
    return apply_daily_public_output_aliases(output)


def project_daily_run_agent_loop_metrics(output: Any) -> dict[str, Any]:
    if not isinstance(output, dict):
        return {}
    metrics = daily_output_value(output, "agent_loop_metrics", default={})
    return dict(metrics) if isinstance(metrics, dict) else {}


__all__ = [
    "apply_daily_run_board_attachment_result",
    "apply_daily_run_public_output_aliases",
    "project_daily_run_agent_loop_metrics",
    "project_daily_run_output_for_board_attachment",
    "project_daily_run_output_for_memory_ingestion",
    "project_daily_run_output_for_persistence",
    "project_daily_run_output_for_run_inspection",
]
