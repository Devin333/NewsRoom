from framework.specs import EdgeSpec, StepSpec, WorkflowPolicySpec, WorkflowSpec


def test_workflow_spec_prd_helpers_and_round_trip() -> None:
    workflow = WorkflowSpec(
        workflow_id="refresh",
        name="Refresh",
        version="1.0",
        steps=[
            StepSpec(step_id="collect", implementation="signal.collect"),
            StepSpec(step_id="normalize", implementation="signal.normalize"),
        ],
        edges=[EdgeSpec(from_step="collect", to_step="normalize")],
        policy=WorkflowPolicySpec(),
    )

    assert workflow.start_step_id == "collect"
    assert workflow.step_ids() == {"collect", "normalize"}
    assert workflow.get_step("normalize").implementation == "signal.normalize"
    assert [step.step_id for step in workflow.entry_steps()] == ["collect"]
    assert [step.step_id for step in workflow.terminal_steps()] == ["normalize"]

    restored = WorkflowSpec.from_dict(workflow.to_dict())
    assert restored.step_by_id("collect").implementation == "signal.collect"


def test_workflow_spec_keeps_legacy_validation_surface() -> None:
    workflow = WorkflowSpec(
        workflow_id="legacy",
        name="Legacy",
        version="1.0",
        start_step_id="start",
        terminal_step_ids=["finish"],
        steps=[
            StepSpec("start", "legacy.start", write_keys=["item"]),
            StepSpec("finish", "legacy.finish", read_keys=["item"]),
        ],
        edges=[EdgeSpec("start-finish", "start", "finish")],
    )

    assert workflow.validation_result().valid is True
    workflow.validate()
