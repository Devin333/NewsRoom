import pytest
from core.framework.specs import (
    ArtifactPolicySpec,
    EdgeCondition,
    EdgeSpec,
    FailurePolicySpec,
    LineagePolicySpec,
    QualityPolicySpec,
    ResourcePolicySpec,
    RetryPolicySpec,
    StepSpec,
    StepType,
    TimeoutPolicySpec,
    WorkflowPolicySpec,
    WorkflowSpec,
    WorkflowSpecError,
    WorkflowSpecRegistry,
    WorkflowTriggerSpec,
)


def test_valid_workflow_spec_passes_validation() -> None:
    spec = WorkflowSpec(
        workflow_id="sample",
        name="Sample",
        version="1.0",
        start_step_id="start",
        steps=[
            StepSpec(step_id="start", implementation="sample.start", step_type=StepType.FUNCTION),
            StepSpec(step_id="finish", implementation="sample.finish"),
        ],
        edges=[EdgeSpec(edge_id="start-to-finish", source_step_id="start", target_step_id="finish")],
    )

    spec.validate()

    assert spec.step_by_id("finish").implementation == "sample.finish"
    assert spec.to_dict()["steps"][0]["step_type"] == "function"
    assert spec.to_dict()["max_step_visits"] == 100


def test_step_spec_serializes_retry_policy() -> None:
    step = StepSpec(
        step_id="flaky",
        implementation="sample.flaky",
        retry_policy=RetryPolicySpec(
            max_retries=2,
            retry_delay_seconds=[1, 5],
            retry_on_error_types=["RuntimeError"],
            no_retry_on_error_types=["ValueError"],
        ),
    )

    payload = step.to_dict()

    assert payload["retry_policy"] == {
        "max_retries": 2,
        "retry_delay_seconds": [1, 5],
        "backoff_strategy": "fixed",
        "retry_on_error_types": ["RuntimeError"],
        "no_retry_on_error_types": ["ValueError"],
    }


def test_step_spec_serializes_timeout_policy() -> None:
    step = StepSpec(
        step_id="slow",
        implementation="sample.slow",
        timeout_policy=TimeoutPolicySpec(timeout_seconds=1.5, on_timeout="retry"),
    )

    payload = step.to_dict()

    assert payload["timeout_policy"] == {
        "timeout_seconds": 1.5,
        "on_timeout": "retry",
    }


def test_edge_spec_imports_legacy_quality_conditions_as_validation_conditions() -> None:
    condition = "qual" + "ity_rewrite_required"
    edge = EdgeSpec(
        edge_id="legacy-validation",
        source_step_id="check",
        target_step_id="retry",
        condition=condition,
    )

    assert edge.condition == EdgeCondition.VALIDATION_RETRY_REQUIRED
    assert edge.to_dict()["condition"] == "validation_retry_required"


def test_step_spec_serializes_failure_policy() -> None:
    step = StepSpec(
        step_id="risky",
        implementation="sample.risky",
        failure_policy=FailurePolicySpec(
            on_failure="fallback_step",
            fallback_step_id="recover",
            allow_partial_success=True,
        ),
    )

    payload = step.to_dict()

    assert payload["failure_policy"] == {
        "on_failure": "fallback_step",
        "fallback_step_id": "recover",
        "mark_as_blocked": False,
        "allow_partial_success": True,
    }


def test_target_state_step_and_workflow_spec_fields_serialize() -> None:
    step = StepSpec(
        step_id="review",
        implementation="human.review",
        step_type=StepType.HUMAN_REVIEW,
        read_keys=["draft_report"],
        write_keys=["human_review_decision"],
        input_schema={"type": "object"},
        output_schema={"type": "object"},
        resource_policy=ResourcePolicySpec(max_cost_usd=0.25, max_parallelism=2),
        quality_policy=QualityPolicySpec(min_editor_score=0.8, allow_rewrite_count=2),
        artifact_policy=ArtifactPolicySpec(write_step_output=True),
        lineage_policy=LineagePolicySpec(input_keys=["draft_report"]),
        idempotent=False,
        client_facing=True,
    )
    spec = WorkflowSpec(
        workflow_id="target-state",
        name="Target State",
        version="1.0",
        trigger=WorkflowTriggerSpec(trigger_type="scheduled", schedule="0 8 * * *"),
        start_step_id="review",
        terminal_step_ids=["review"],
        input_schema={"type": "object"},
        output_schema={"type": "object"},
        policies=WorkflowPolicySpec(
            resource_policy=ResourcePolicySpec(max_cost_usd=1.0),
            quality_policy=QualityPolicySpec(min_citation_coverage=0.9),
        ),
        steps=[step],
    )

    payload = spec.to_dict()

    assert payload["trigger"]["trigger_type"] == "scheduled"
    assert payload["policies"]["quality_policy"]["min_citation_coverage"] == 0.9
    assert payload["steps"][0]["step_type"] == "human_review"
    assert payload["steps"][0]["input_schema"] == {"type": "object"}
    assert payload["steps"][0]["resource_policy"]["max_parallelism"] == 2
    assert payload["steps"][0]["quality_policy"]["min_editor_score"] == 0.8
    assert payload["steps"][0]["artifact_policy"]["write_step_output"] is True
    assert payload["steps"][0]["lineage_policy"]["input_keys"] == ["draft_report"]
    assert payload["steps"][0]["idempotent"] is False
    assert payload["steps"][0]["client_facing"] is True


def test_workflow_validation_result_reports_errors_and_warnings() -> None:
    spec = WorkflowSpec(
        workflow_id="validation",
        name="Validation",
        version="1.0",
        start_step_id="review",
        steps=[
            StepSpec(
                step_id="review",
                implementation="human.review",
                step_type=StepType.HUMAN_REVIEW,
                metadata={"api_key": "do-not-store"},
            )
        ],
    )

    result = spec.validation_result(registered_step_types=[StepType.FUNCTION])

    assert result.passed is False
    assert result.errors[0].code == "step_runner_missing"
    assert result.errors[0].step_id == "review"
    assert result.warnings[0].code == "secret_like_spec_field"
    assert result.warnings[0].step_id == "review"


def test_workflow_spec_registry_pins_versions_and_latest_active() -> None:
    registry = WorkflowSpecRegistry()
    v1 = WorkflowSpec(
        workflow_id="daily",
        name="Daily",
        version="1.0",
        start_step_id="start",
        steps=[StepSpec(step_id="start", implementation="daily.start")],
    )
    v2 = WorkflowSpec(
        workflow_id="daily",
        name="Daily",
        version="2.0",
        start_step_id="start",
        steps=[StepSpec(step_id="start", implementation="daily.start")],
    )

    registry.register(v1)
    registry.register(v2)
    registry.deprecate("daily", "1.0")

    assert registry.get("daily", "1.0") is v1
    assert registry.latest("daily") is v2
    assert registry.list_versions("daily") == ["1.0", "2.0"]
    assert registry.is_deprecated("daily", "1.0") is True


def test_retry_policy_rejects_negative_values() -> None:
    with pytest.raises(WorkflowSpecError, match="max_retries must be non-negative"):
        RetryPolicySpec(max_retries=-1)

    with pytest.raises(WorkflowSpecError, match="retry_delay_seconds"):
        RetryPolicySpec(retry_delay_seconds=[-1])


def test_timeout_policy_rejects_invalid_values() -> None:
    with pytest.raises(WorkflowSpecError, match="timeout_seconds must be positive"):
        TimeoutPolicySpec(timeout_seconds=0)

    with pytest.raises(WorkflowSpecError, match="on_timeout"):
        TimeoutPolicySpec(timeout_seconds=1, on_timeout="pause")


def test_workflow_spec_rejects_non_positive_step_visit_limit() -> None:
    spec = WorkflowSpec(
        workflow_id="sample",
        name="Sample",
        version="1.0",
        start_step_id="start",
        max_step_visits=0,
        steps=[StepSpec(step_id="start", implementation="sample.start")],
    )

    with pytest.raises(WorkflowSpecError, match="max_step_visits must be positive"):
        spec.validate()


def test_workflow_spec_rejects_missing_start_step() -> None:
    spec = WorkflowSpec(
        workflow_id="sample",
        name="Sample",
        version="1.0",
        start_step_id="missing",
        steps=[StepSpec(step_id="start", implementation="sample.start")],
    )

    with pytest.raises(WorkflowSpecError, match="start step does not exist"):
        spec.validate()


def test_workflow_spec_rejects_duplicate_step_ids() -> None:
    spec = WorkflowSpec(
        workflow_id="sample",
        name="Sample",
        version="1.0",
        start_step_id="same",
        steps=[
            StepSpec(step_id="same", implementation="sample.one"),
            StepSpec(step_id="same", implementation="sample.two"),
        ],
    )

    with pytest.raises(WorkflowSpecError, match="duplicate step ids"):
        spec.validate()


def test_workflow_spec_rejects_missing_edge_endpoint() -> None:
    spec = WorkflowSpec(
        workflow_id="sample",
        name="Sample",
        version="1.0",
        start_step_id="start",
        steps=[StepSpec(step_id="start", implementation="sample.start")],
        edges=[EdgeSpec(edge_id="bad-edge", source_step_id="start", target_step_id="missing")],
    )

    with pytest.raises(WorkflowSpecError, match="missing target step"):
        spec.validate()


def test_workflow_spec_rejects_missing_failure_fallback_step() -> None:
    spec = WorkflowSpec(
        workflow_id="sample",
        name="Sample",
        version="1.0",
        start_step_id="start",
        steps=[
            StepSpec(
                step_id="start",
                implementation="sample.start",
                failure_policy=FailurePolicySpec(fallback_step_id="missing"),
            )
        ],
    )

    with pytest.raises(WorkflowSpecError, match="fallback step does not exist"):
        spec.validate()


def test_workflow_spec_rejects_required_output_not_declared_in_write_keys() -> None:
    spec = WorkflowSpec(
        workflow_id="sample",
        name="Sample",
        version="1.0",
        start_step_id="start",
        steps=[
            StepSpec(
                step_id="start",
                implementation="sample.start",
                write_keys=["other"],
                required_output_keys=["missing"],
            )
        ],
    )

    with pytest.raises(WorkflowSpecError, match="required_output_keys"):
        spec.validate()


def test_workflow_spec_rejects_read_key_without_upstream_producer() -> None:
    spec = WorkflowSpec(
        workflow_id="sample",
        name="Sample",
        version="1.0",
        start_step_id="start",
        steps=[
            StepSpec(step_id="start", implementation="sample.start", write_keys=["plan"]),
            StepSpec(
                step_id="finish",
                implementation="sample.finish",
                read_keys=["missing"],
            ),
        ],
        edges=[EdgeSpec(edge_id="start-to-finish", source_step_id="start", target_step_id="finish")],
    )

    with pytest.raises(WorkflowSpecError, match="read_keys are not produced"):
        spec.validate()


def test_workflow_spec_rejects_unreachable_terminal_step() -> None:
    spec = WorkflowSpec(
        workflow_id="sample",
        name="Sample",
        version="1.0",
        start_step_id="start",
        terminal_step_ids=["orphan"],
        steps=[
            StepSpec(step_id="start", implementation="sample.start"),
            StepSpec(step_id="orphan", implementation="sample.orphan"),
        ],
    )

    with pytest.raises(WorkflowSpecError, match="terminal step is not reachable"):
        spec.validate()


def test_workflow_spec_accepts_terminal_step_reachable_by_fallback_policy() -> None:
    spec = WorkflowSpec(
        workflow_id="sample",
        name="Sample",
        version="1.0",
        start_step_id="start",
        terminal_step_ids=["recover"],
        steps=[
            StepSpec(
                step_id="start",
                implementation="sample.start",
                failure_policy=FailurePolicySpec(fallback_step_id="recover"),
            ),
            StepSpec(step_id="recover", implementation="sample.recover"),
        ],
    )

    spec.validate()


def test_workflow_spec_rejects_conditional_edge_without_expression() -> None:
    spec = WorkflowSpec(
        workflow_id="sample",
        name="Sample",
        version="1.0",
        start_step_id="start",
        steps=[
            StepSpec(step_id="start", implementation="sample.start"),
            StepSpec(step_id="finish", implementation="sample.finish"),
        ],
        edges=[
            EdgeSpec(
                edge_id="conditional",
                source_step_id="start",
                target_step_id="finish",
                condition=EdgeCondition.CONDITIONAL,
            )
        ],
    )

    with pytest.raises(WorkflowSpecError, match="requires condition_expr"):
        spec.validate()
