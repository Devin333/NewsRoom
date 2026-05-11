from core.framework.specs import StepStatus
from core.framework.workflow import StepOutcome
from storage.artifacts import ArtifactRef


def test_step_outcome_serializes_artifact_refs() -> None:
    outcome = StepOutcome(
        status=StepStatus.SUCCEEDED,
        outputs={"report": "ready"},
        artifacts=[
            ArtifactRef(
                artifact_id="artifact-1",
                run_id="run-1",
                step_id="draft",
                artifact_type="step_output",
                path="steps/draft/output.json",
                content_type="application/json",
            )
        ],
    )

    payload = outcome.to_dict()

    assert payload["artifacts"][0]["artifact_id"] == "artifact-1"
    assert payload["artifacts"][0]["step_id"] == "draft"
    assert payload["artifacts"][0]["path"] == "steps/draft/output.json"
