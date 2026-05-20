from framework.specs import (
    ArtifactPolicySpec,
    LineagePolicySpec,
    QualityPolicySpec,
    ResourcePolicySpec,
    RetryPolicySpec,
    TimeoutPolicySpec,
    WorkflowPolicySpec,
)


def test_retry_policy_prd_fields_and_legacy_fields_coexist() -> None:
    retry = RetryPolicySpec(max_attempts=3, backoff_seconds=2.0, backoff_multiplier=2.0)

    assert retry.delay_for_attempt(3) == 8.0
    assert retry.to_dict()["max_attempts"] == 3
    assert retry.max_retries == 0


def test_timeout_resource_quality_artifact_lineage_prd_fields() -> None:
    timeout = TimeoutPolicySpec(timeout_seconds=30)
    resource = ResourcePolicySpec(max_memory_mb=512, max_runtime_seconds=45, max_cost_usd=1.25)
    quality = QualityPolicySpec(required=True, min_score=0.8, evaluator="editor")
    artifact = ArtifactPolicySpec(publish_outputs=True, required_artifacts=["report"])
    lineage = LineagePolicySpec(capture_inputs=True, capture_outputs=False)

    assert timeout.has_timeout() is True
    assert resource.to_dict()["max_memory_mb"] == 512
    assert quality.to_dict()["min_score"] == 0.8
    assert artifact.to_dict()["required_artifacts"] == ["report"]
    assert lineage.to_dict()["capture_outputs"] is False


def test_workflow_policy_accepts_prd_aliases() -> None:
    policy = WorkflowPolicySpec(
        retry=RetryPolicySpec(max_attempts=2),
        resource=ResourcePolicySpec(max_memory_mb=128),
        artifact=ArtifactPolicySpec(publish_outputs=False),
        lineage=LineagePolicySpec(capture_inputs=False),
    )
    restored = WorkflowPolicySpec.from_dict(policy.to_dict())

    assert policy.retry.max_attempts == 2
    assert policy.resource.max_memory_mb == 128
    assert restored.artifact.publish_outputs is False
    assert restored.lineage.capture_inputs is False
