"""Canonical values shared by Projects Lab contract tests."""

from backend.projects.lab import (
    LAB_CONTRACT_VERSION,
    LAB_NEXT_ACTION_VALUES,
    LAB_WORKFLOW_STAGE_VALUES,
)


LAB_CONTRACT_FIXTURE = {
    "version": LAB_CONTRACT_VERSION,
    "stages": LAB_WORKFLOW_STAGE_VALUES,
    "next_actions": LAB_NEXT_ACTION_VALUES,
    "error_codes": (
        "invalid_project_lab_request",
        "project_lab_session_not_found",
        "project_lab_question_not_found",
        "invalid_project_lab_answer",
        "project_lab_node_not_found",
        "lab_session_not_ready",
        "lab_solution_missing",
    ),
}
