import json

from core.framework.artifacts import ArtifactManager
from core.framework.specs import EdgeCondition, EdgeSpec, StepSpec, StepType, WorkflowSpec, WorkflowStatus
from core.framework.workflow import (
    FunctionStepRegistry,
    FunctionStepRunner,
    HumanReviewStepRunner,
    StepRunnerRegistry,
    WorkflowExecutor,
)
from storage.checkpoint import LocalJsonCheckpointStore


def test_human_review_checkpoint_resume_preserves_state_and_skips_completed_prefix(tmp_path) -> None:
    calls = {"prepare": 0, "finalize": 0}
    functions = FunctionStepRegistry()

    def prepare(buffer):
        calls["prepare"] += 1
        return {"draft": f"draft:{buffer.read('request')['topic']}"}

    def finalize(buffer):
        calls["finalize"] += 1
        return {
            "report": (
                f"{buffer.read('draft')}:{buffer.read('human_review_decision')['decision']}"
            )
        }

    functions.register("sample.prepare", prepare)
    functions.register("sample.finalize", finalize)
    registry = StepRunnerRegistry.with_function_runner(FunctionStepRunner(functions))
    registry.register(StepType.HUMAN_REVIEW, HumanReviewStepRunner())
    checkpoint_store = LocalJsonCheckpointStore(tmp_path / "checkpoints")
    spec = WorkflowSpec(
        workflow_id="human-e2e",
        name="Human E2E",
        version="1.0",
        start_step_id="prepare",
        input_schema={"properties": {"human_review_decision": {"type": "object"}}},
        steps=[
            StepSpec(
                "prepare",
                "sample.prepare",
                read_keys=["request"],
                write_keys=["draft"],
                required_output_keys=["draft"],
            ),
            StepSpec(
                "review",
                "human.review",
                step_type=StepType.HUMAN_REVIEW,
                read_keys=["draft", "human_review_decision"],
                write_keys=["human_review_request"],
            ),
            StepSpec(
                "finalize",
                "sample.finalize",
                read_keys=["draft", "human_review_decision"],
                write_keys=["report"],
                required_output_keys=["report"],
            ),
        ],
        edges=[
            EdgeSpec("prepare-review", "prepare", "review"),
            EdgeSpec("review-finalize", "review", "finalize", condition=EdgeCondition.HUMAN_APPROVED),
        ],
    )
    executor = WorkflowExecutor(
        function_step_runner=None,
        step_runner_registry=registry,
        artifact_manager=ArtifactManager(tmp_path / "runs"),
        checkpoint_store=checkpoint_store,
    )

    paused = executor.execute(spec, {"topic": "ai"}, profile="test", run_id="run-human-e2e")
    checkpoint = checkpoint_store.get_latest_checkpoint("run-human-e2e")
    paused_manifest = json.loads(
        (tmp_path / "runs" / "run-human-e2e" / "manifest.json").read_text(encoding="utf-8")
    )

    assert paused.status == WorkflowStatus.WAITING_FOR_HUMAN
    assert paused_manifest["latest_checkpoint_id"] == checkpoint.checkpoint_id
    assert checkpoint.current_step_ids == ["review"]
    assert checkpoint.data_buffer_snapshot["draft"] == "draft:ai"
    assert set(checkpoint.step_results) == {"prepare", "review"}
    assert checkpoint.path == ["prepare", "review"]

    resumed = executor.resume_from_checkpoint(
        spec,
        checkpoint,
        profile="test",
        run_id="run-human-e2e-resumed",
        buffer_updates={"human_review_decision": {"decision": "approved"}},
    )
    resumed_manifest = json.loads(
        (tmp_path / "runs" / "run-human-e2e-resumed" / "manifest.json").read_text(encoding="utf-8")
    )
    resumed_events = [
        json.loads(line)["event_type"]
        for line in (tmp_path / "runs" / "run-human-e2e-resumed" / "events.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]

    assert resumed.status == WorkflowStatus.SUCCEEDED
    assert resumed.output["report"] == "draft:ai:approved"
    assert calls == {"prepare": 1, "finalize": 1}
    assert resumed.path == ["prepare", "review", "review", "finalize"]
    assert resumed_manifest["resumed_from_checkpoint_id"] == checkpoint.checkpoint_id
    assert resumed_events[:2] == ["workflow_resumed", "checkpoint_restored"]
