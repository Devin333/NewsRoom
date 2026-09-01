"""Canonical values shared by Projects Lab contract tests."""

LAB_CONTRACT_FIXTURE = {
    "version": "projects-lab/v1",
    "stages": (
        "clarifying_requirements",
        "ready_to_generate",
        "solution_generated",
        "solution_saved",
        "solution_adopted",
        "solution_archived",
    ),
    "next_actions": (
        "answer_question",
        "generate_solution",
        "review_solution",
        "save_solution",
        "none",
    ),
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
