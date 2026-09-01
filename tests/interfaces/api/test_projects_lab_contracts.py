from interfaces.api.openapi import export_openapi_schema
from tests.backend.projects.fixtures import LAB_CONTRACT_FIXTURE


def test_projects_lab_openapi_publishes_contract_version_and_success_fields() -> None:
    schema = export_openapi_schema()

    assert schema["info"]["x-projects-lab-contract-version"] == LAB_CONTRACT_FIXTURE["version"]
    start = schema["paths"]["/api/v1/projects/lab/sessions"]["post"]
    example = start["responses"]["200"]["content"]["application/json"]["example"]
    session = example["data"]["session"]
    assert {
        "current_stage",
        "next_action",
        "can_generate_solution",
        "unanswered_question_ids",
    } <= session.keys()


def test_projects_lab_openapi_publishes_status_specific_error_examples() -> None:
    schema = export_openapi_schema()
    generate = schema["paths"]["/api/v1/projects/lab/sessions/{session_id}/generate-solution"]["post"]

    conflict = generate["responses"]["409"]["content"]["application/json"]["example"]
    assert conflict["error"]["code"] == "lab_session_not_ready"
    assert conflict["error"]["details"]["unanswered_question_ids"] == ["question-goal"]
    assert conflict["error"]["user_action_required"] is True

    answer = schema["paths"]["/api/v1/projects/lab/sessions/{session_id}/answer"]["post"]
    invalid = answer["responses"]["422"]["content"]["application/json"]["example"]
    assert invalid["error"]["code"] == "invalid_project_lab_answer"


def test_projects_lab_error_fixture_codes_are_all_documented() -> None:
    schema = export_openapi_schema()
    documented = set()
    for path, operations in schema["paths"].items():
        if "/api/v1/projects/lab/" not in path:
            continue
        for operation in operations.values():
            if not isinstance(operation, dict):
                continue
            for response in operation.get("responses", {}).values():
                example = response.get("content", {}).get("application/json", {}).get("example", {})
                code = example.get("error", {}).get("code")
                if code:
                    documented.add(code)
    assert set(LAB_CONTRACT_FIXTURE["error_codes"]) <= documented
