import pytest

from framework.specs import StepSpec, StepType, WorkflowSpecError


def test_step_type_from_value_normalizes_supported_values() -> None:
    assert StepType.from_value("function") is StepType.FUNCTION
    assert StepType.from_value(StepType.TOOL_CALL) is StepType.TOOL_CALL
    assert StepType.TOOL_CALL.value == "tool_call"
    with pytest.raises(ValueError, match="tool"):
        StepType.from_value("tool")


def test_step_status_helpers_and_input_output_keys() -> None:
    step = StepSpec(
        step_id="normalize",
        name="Normalize",
        step_type=StepType.FUNCTION,
        config={"implementation": "signal.normalize"},
        inputs={"raw": "$.raw"},
        outputs={"signal": "$.signal"},
        read_keys=["request"],
        write_keys=["normalized"],
    )

    assert step.implementation == "signal.normalize"
    assert step.input_keys() == {"raw", "request"}
    assert step.output_keys() == {"signal", "normalized"}
    assert step.to_dict()["config"] == {"implementation": "signal.normalize"}


def test_step_from_dict_keeps_legacy_runtime_fields() -> None:
    step = StepSpec.from_dict(
        {
            "step_id": "persist",
            "implementation": "persist.output",
            "step_type": "persist",
            "read_keys": ["report"],
            "write_keys": ["artifact_ref"],
        }
    )

    assert step.step_type is StepType.PERSIST
    assert step.input_keys() == {"report"}


def test_step_rejects_invalid_mapping_fields() -> None:
    with pytest.raises(WorkflowSpecError, match="inputs must be an object"):
        StepSpec(step_id="bad", implementation="bad.impl", inputs=[])  # type: ignore[arg-type]
