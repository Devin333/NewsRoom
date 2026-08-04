from __future__ import annotations

import pytest

from framework.agent.artifacts import ArtifactManager
from framework.specs import StepSpec, StepStatus, StepType
from framework.workflow.buffer import DataBuffer
from framework.workflow.runners.artifact import (
    ARTIFACT_STEP_RESERVED_METADATA_KEYS,
    ArtifactStepRunner,
)


@pytest.mark.parametrize("reserved_key", sorted(ARTIFACT_STEP_RESERVED_METADATA_KEYS))
def test_artifact_step_rejects_reserved_nested_metadata(
    tmp_path,
    reserved_key: str,
) -> None:
    step = StepSpec(
        step_id="artifact-step",
        step_type=StepType.ARTIFACT,
        write_keys=["artifact_ref"],
        metadata={
            "content": {"ok": True},
            "artifact_metadata": {reserved_key: "forged"},
        },
    )
    buffer = DataBuffer().scope(
        step.read_keys,
        step.write_keys,
        step_id=step.step_id,
    )
    runner = ArtifactStepRunner(ArtifactManager(tmp_path), run_id="run-1")

    outcome = runner.run(step, buffer)

    assert outcome.status == StepStatus.FAILED
    assert outcome.artifacts == []
    assert not buffer.exists("artifact_ref")
    assert not tmp_path.exists() or not any(tmp_path.rglob("*"))


def test_artifact_step_accepts_top_level_system_and_custom_metadata(tmp_path) -> None:
    step = StepSpec(
        step_id="artifact-step",
        step_type=StepType.ARTIFACT,
        write_keys=["artifact_ref"],
        metadata={
            "content": {"ok": True},
            "artifact_id": "custom:logical-id",
            "artifact_type": "json",
            "relative_path": "steps/artifact-step/custom.json",
            "content_type": "application/json",
            "redacted": False,
            "artifact_metadata": {"source_id": "source-1"},
        },
    )
    buffer = DataBuffer().scope(
        step.read_keys,
        step.write_keys,
        step_id=step.step_id,
    )
    runner = ArtifactStepRunner(ArtifactManager(tmp_path), run_id="run-1")

    outcome = runner.run(step, buffer)

    assert outcome.status == StepStatus.SUCCEEDED
    assert outcome.artifacts[0].artifact_id == "custom:logical-id"
    assert outcome.artifacts[0].redacted is False
    assert buffer.buffer.snapshot(redacted=False).values["artifact_ref"]["metadata"]["source_id"] == "source-1"
    assert (tmp_path / "run-1" / "steps" / "artifact-step" / "custom.json").exists()
