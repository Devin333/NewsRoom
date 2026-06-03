from __future__ import annotations

from typing import Any

from business.boards.cross_board.workflows.daily_intelligence.output_projection import (
    apply_daily_board_attachment_result,
    apply_daily_public_output_aliases,
    project_daily_output_for_board_attachment,
    project_daily_output_for_memory_ingestion,
)


def project_daily_run_output_for_memory_ingestion(output: Any) -> dict[str, Any]:
    return project_daily_output_for_memory_ingestion(output)


def project_daily_run_output_for_board_attachment(output: dict[str, Any]) -> dict[str, Any]:
    return project_daily_output_for_board_attachment(output)


def apply_daily_run_board_attachment_result(
    output: dict[str, Any],
    board_output: dict[str, Any],
) -> dict[str, Any]:
    return apply_daily_board_attachment_result(output, board_output)


def apply_daily_run_public_output_aliases(output: dict[str, Any]) -> dict[str, Any]:
    return apply_daily_public_output_aliases(output)


__all__ = [
    "apply_daily_run_board_attachment_result",
    "apply_daily_run_public_output_aliases",
    "project_daily_run_output_for_board_attachment",
    "project_daily_run_output_for_memory_ingestion",
]
