from framework.specs import (
    EdgeSpec,
    StepSpec,
    ValidationResult,
    WorkflowSpec,
    WorkflowSpecValidator,
)


def test_validation_result_is_immutable_builder() -> None:
    result = ValidationResult()
    failed = result.add_error("missing", "missing field", path="workflow_id")
    warned = failed.add_warning("deprecated", "deprecated field", path="policy")

    assert result.valid is True
    assert failed.valid is False
    assert warned.to_dict()["errors"][0]["path"] == "workflow_id"
    assert warned.to_dict()["warnings"][0]["path"] == "policy"


def test_workflow_spec_validator_delegates_declarative_validation() -> None:
    workflow = WorkflowSpec(
        workflow_id="bad",
        name="Bad",
        version="1.0",
        start_step_id="start",
        steps=[StepSpec("start", "bad.start")],
        edges=[EdgeSpec("bad-edge", "start", "missing")],
    )

    result = WorkflowSpecValidator().validate(workflow)

    assert result.valid is False
    assert {error.code for error in result.errors} == {"edge_target_missing"}
