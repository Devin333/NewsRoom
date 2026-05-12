from core.framework.artifacts import ArtifactManager
from core.framework.tools import (
    ToolCall,
    ToolExecutor,
    ToolPolicy,
    ToolRegistry,
    ToolStatus,
    register_artifact_tools,
)


def test_artifact_tools_write_and_load_real_json_file(tmp_path) -> None:
    artifact_manager = ArtifactManager(tmp_path)
    artifact_manager.start_run("artifact-run")
    registry = ToolRegistry()
    register_artifact_tools(registry, artifact_manager=artifact_manager, run_id="artifact-run")
    executor = ToolExecutor(registry)

    write_observation = executor.execute(
        ToolCall(
            tool_name="artifact.write",
            arguments={
                "path": "notes/result.json",
                "content": {"summary": "ok", "items": [1, 2]},
            },
        ),
        ToolPolicy(
            allowed_tools=["artifact.write"],
            require_approval_for_side_effects=False,
        ),
    )
    load_observation = executor.execute(
        ToolCall(tool_name="artifact.load", arguments={"path": "notes/result.json"}),
        ToolPolicy(allowed_tools=["artifact.load"]),
    )

    artifact_path = tmp_path / "artifact-run" / "notes" / "result.json"

    assert write_observation.status == ToolStatus.SUCCEEDED
    assert load_observation.status == ToolStatus.SUCCEEDED
    assert artifact_path.exists()
    assert write_observation.result.output["relative_path"] == "notes/result.json"
    assert load_observation.result.output["content"] == {"items": [1, 2], "summary": "ok"}
    assert load_observation.result.output["content_type"] == "application/json"


def test_artifact_load_rejects_path_traversal(tmp_path) -> None:
    artifact_manager = ArtifactManager(tmp_path)
    artifact_manager.start_run("artifact-run")
    registry = ToolRegistry()
    register_artifact_tools(registry, artifact_manager=artifact_manager, run_id="artifact-run")
    executor = ToolExecutor(registry)

    observation = executor.execute(
        ToolCall(tool_name="artifact.load", arguments={"path": "../outside.json"}),
        ToolPolicy(allowed_tools=["artifact.load"]),
    )

    assert observation.status == ToolStatus.FAILED
    assert observation.result.error_type == "ValueError"
    assert "relative to the run directory" in (observation.result.error_message or "")
