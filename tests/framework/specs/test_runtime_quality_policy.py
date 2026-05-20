from __future__ import annotations

from framework.specs import (
    EvaluationPolicySpec,
    GatePolicySpec,
    RuntimeQualityPolicySpec,
    StepSpec,
    TracePolicySpec,
    WorkflowPolicySpec,
    WorkflowSpec,
)


def test_runtime_quality_policy_defaults_and_round_trip() -> None:
    policy = RuntimeQualityPolicySpec()
    restored = RuntimeQualityPolicySpec.from_dict(policy.to_dict())

    assert restored.trace.enabled is True
    assert restored.trace.level == "standard"
    assert restored.evaluation.enabled is False
    assert restored.gate.mode == "and"


def test_workflow_policy_mounts_runtime_quality() -> None:
    policy = WorkflowPolicySpec(
        runtime_quality={
            "trace": {"level": "full", "max_payload_bytes": 1024},
            "evaluation": {"enabled": True, "required_output_keys": ["report"]},
            "gate": {"mode": "warn_only", "dimensions": ["trace", "correctness"]},
        }
    )

    assert policy.runtime_quality.trace.level == "full"
    assert policy.runtime_quality.evaluation.required_output_keys == ["report"]
    assert policy.to_dict()["runtime_quality"]["gate"]["mode"] == "warn_only"


def test_step_runtime_quality_override_serializes() -> None:
    step = StepSpec(
        step_id="s1",
        write_keys=["ok"],
        runtime_quality=RuntimeQualityPolicySpec(
            trace=TracePolicySpec(level="minimal"),
            evaluation=EvaluationPolicySpec(enabled=True, required_output_keys=["ok"]),
            gate=GatePolicySpec(mode="warn_only"),
        ),
    )
    workflow = WorkflowSpec(
        workflow_id="wf",
        name="Workflow",
        version="1.0",
        steps=[step],
        terminal_step_ids=["s1"],
    )

    assert workflow.steps[0].runtime_quality.trace.level == "minimal"
    assert workflow.steps[0].to_dict()["runtime_quality"]["evaluation"]["required_output_keys"] == ["ok"]
