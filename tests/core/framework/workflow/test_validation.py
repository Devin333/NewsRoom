from core.framework.specs import (
    EdgeCondition,
    EdgeSpec,
    StepSpec,
    StepType,
    WorkflowSpec,
)


def test_validation_rejects_missing_start_step() -> None:
    result = WorkflowSpec(
        workflow_id="bad-start",
        name="Bad Start",
        version="1.0",
        start_step_id="missing",
        steps=[StepSpec("start", "sample.start")],
    ).validation_result()

    assert result.errors[0].code == "start_step_missing"


def test_validation_rejects_missing_edge_source_and_target() -> None:
    result = WorkflowSpec(
        workflow_id="bad-edge",
        name="Bad Edge",
        version="1.0",
        start_step_id="start",
        steps=[StepSpec("start", "sample.start")],
        edges=[EdgeSpec("bad", "missing-source", "missing-target")],
    ).validation_result()

    assert {error.code for error in result.errors} >= {
        "edge_source_missing",
        "edge_target_missing",
    }


def test_validation_rejects_unavailable_read_key_in_strict_mode() -> None:
    spec = WorkflowSpec(
        workflow_id="missing-read",
        name="Missing Read",
        version="1.0",
        start_step_id="start",
        steps=[
            StepSpec("start", "sample.start", write_keys=["plan"]),
            StepSpec("finish", "sample.finish", read_keys=["missing"]),
        ],
        edges=[EdgeSpec("start-finish", "start", "finish")],
    )

    result = spec.validation_result(strict=True)

    assert {error.code for error in result.errors} >= {
        "read_keys_unavailable",
        "read_keys_not_available_on_all_paths",
    }


def test_strict_validation_rejects_read_key_not_available_on_every_branch() -> None:
    spec = WorkflowSpec(
        workflow_id="branch-read",
        name="Branch Read",
        version="1.0",
        start_step_id="start",
        steps=[
            StepSpec("start", "sample.start"),
            StepSpec("left", "sample.left", write_keys=["left_value"]),
            StepSpec("right", "sample.right"),
            StepSpec("join", "sample.join", read_keys=["left_value"]),
        ],
        edges=[
            EdgeSpec("start-left", "start", "left", condition=EdgeCondition.ALWAYS),
            EdgeSpec("start-right", "start", "right", condition=EdgeCondition.ALWAYS),
            EdgeSpec("left-join", "left", "join"),
            EdgeSpec("right-join", "right", "join"),
        ],
    )

    result = spec.validation_result(strict=True)

    assert "read_keys_not_available_on_all_paths" in {error.code for error in result.errors}


def test_strict_validation_rejects_parallel_fanout_write_conflict() -> None:
    spec = WorkflowSpec(
        workflow_id="fanout-conflict",
        name="Fanout Conflict",
        version="1.0",
        start_step_id="start",
        steps=[
            StepSpec("start", "sample.start"),
            StepSpec("left", "sample.left", write_keys=["shared"]),
            StepSpec("right", "sample.right", write_keys=["shared"]),
        ],
        edges=[
            EdgeSpec("start-left", "start", "left", condition=EdgeCondition.ALWAYS),
            EdgeSpec("start-right", "start", "right", condition=EdgeCondition.ALWAYS),
        ],
    )

    result = spec.validation_result(strict=True)

    assert "parallel_fanout_write_conflict" in {error.code for error in result.errors}


def test_validation_rejects_missing_registered_step_runner() -> None:
    spec = WorkflowSpec(
        workflow_id="missing-runner",
        name="Missing Runner",
        version="1.0",
        start_step_id="review",
        steps=[StepSpec("review", "human.review", step_type=StepType.HUMAN_REVIEW)],
    )

    result = spec.validation_result(registered_step_types=[StepType.FUNCTION])

    assert result.errors[0].code == "step_runner_missing"


def test_strict_validation_rejects_human_review_without_checkpoint_or_pause_strategy() -> None:
    spec = WorkflowSpec(
        workflow_id="human-strict",
        name="Human Strict",
        version="1.0",
        start_step_id="review",
        steps=[StepSpec("review", "human.review", step_type=StepType.HUMAN_REVIEW)],
    )

    result = spec.validation_result(strict=True)

    assert "human_review_checkpoint_required" in {error.code for error in result.errors}


def test_validation_allows_human_review_with_checkpoint_store() -> None:
    spec = WorkflowSpec(
        workflow_id="human-strict",
        name="Human Strict",
        version="1.0",
        start_step_id="review",
        steps=[StepSpec("review", "human.review", step_type=StepType.HUMAN_REVIEW)],
    )

    result = spec.validation_result(
        strict=True,
        checkpoint_store_available=True,
        registered_step_types=[StepType.HUMAN_REVIEW],
    )

    assert result.passed is True


def test_validation_rejects_llm_decide_for_governance_decision() -> None:
    spec = WorkflowSpec(
        workflow_id="bad-llm-edge",
        name="Bad LLM Edge",
        version="1.0",
        start_step_id="draft",
        steps=[
            StepSpec("draft", "sample.draft"),
            StepSpec("publish", "sample.publish"),
        ],
        edges=[
            EdgeSpec(
                "llm-publish",
                "draft",
                "publish",
                condition=EdgeCondition.LLM_DECIDE,
                metadata={"purpose": "publish approval"},
            )
        ],
    )

    result = spec.validation_result()

    assert "llm_decide_governance_forbidden" in {error.code for error in result.errors}


def test_validation_rejects_parallel_group_branch_write_conflict() -> None:
    spec = WorkflowSpec(
        workflow_id="parallel-conflict",
        name="Parallel Conflict",
        version="1.0",
        start_step_id="parallel",
        steps=[
            StepSpec(
                "parallel",
                "parallel.sources",
                step_type=StepType.PARALLEL_GROUP,
                write_keys=["items"],
                metadata={
                    "branches": [
                        {"branch_id": "left", "implementation": "left", "write_keys": ["items"]},
                        {"branch_id": "right", "implementation": "right", "write_keys": ["items"]},
                    ]
                },
            )
        ],
    )

    result = spec.validation_result()

    assert "parallel_write_conflict" in {error.code for error in result.errors}
