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


def test_workflow_strict_read_key_validation_accepts_bounded_feedback_cycle() -> None:
    workflow = WorkflowSpec(
        workflow_id="feedback-loop",
        name="Feedback Loop",
        version="1.0",
        start_step_id="collect",
        terminal_step_ids=["finish"],
        steps=[
            StepSpec("collect", "collect", write_keys=["evidence"]),
            StepSpec("plan", "plan", read_keys=["evidence"], write_keys=["plan"]),
            StepSpec(
                "write",
                "write",
                read_keys=["evidence", "plan"],
                write_keys=["draft"],
            ),
            StepSpec("verify", "verify", read_keys=["draft"], write_keys=["feedback"]),
            StepSpec(
                "finish",
                "finish",
                read_keys=["draft", "feedback"],
            ),
        ],
        edges=[
            EdgeSpec("collect-plan", "collect", "plan"),
            EdgeSpec("plan-write", "plan", "write"),
            EdgeSpec("write-verify", "write", "verify"),
            EdgeSpec("verify-write", "verify", "write"),
            EdgeSpec("verify-finish", "verify", "finish"),
        ],
    )

    result = workflow.validation_result(strict=True)

    assert result.valid is True
