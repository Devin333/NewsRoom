from __future__ import annotations

import pytest

from framework.agent.artifacts import ArtifactManager
from framework.tool import ToolCall, ToolExecutor, ToolPolicy, ToolRegistry, ToolStatus
from framework.tool.builtin.artifact import register_artifact_tools
from framework.shared.graph_identity import GraphExecutionIdentity


def test_artifact_tools_write_then_load_nested_json(tmp_path) -> None:
    manager = ArtifactManager(tmp_path)
    manager.start_run("run-1")
    executor = _executor(manager, "run-1")

    written = _execute(
        executor,
        "artifact.write",
        {"path": "steps/s1/output.json", "content": {"ok": True}},
    )
    loaded = _execute(
        executor,
        "artifact.load",
        {"path": "steps/s1/output.json"},
    )

    assert written.status == ToolStatus.SUCCEEDED
    assert loaded.status == ToolStatus.SUCCEEDED
    assert loaded.output["content"] == {"ok": True}


def test_artifact_tool_registration_requires_exact_graph_identity(tmp_path) -> None:
    with pytest.raises(TypeError, match="execution_identity"):
        register_artifact_tools(
            ToolRegistry(),
            artifact_manager=ArtifactManager(tmp_path),
            execution_identity=None,
        )


@pytest.mark.parametrize(
    "tool_name,arguments",
    [
        ("artifact.write", {"path": "../outside.json", "content": {"leaked": True}}),
        ("artifact.load", {"path": "C:outside.json"}),
        ("artifact.search", {"path_prefix": "\\\\server\\share"}),
        ("artifact.search", {"path_prefix": "a:stream"}),
    ],
)
def test_artifact_tools_reject_unsafe_paths_without_external_access(
    tmp_path,
    tool_name,
    arguments,
) -> None:
    manager = ArtifactManager(tmp_path / "runs")
    manager.start_run("run-1")
    outside = tmp_path / "outside.json"
    outside.write_text('{"secret": true}', encoding="utf-8")
    executor = _executor(manager, "run-1")

    result = _execute(executor, tool_name, arguments)

    assert result.status == ToolStatus.FAILED
    assert result.error_type == "ArtifactPathError"
    assert outside.read_text(encoding="utf-8") == '{"secret": true}'


@pytest.mark.parametrize("tool_name", ["artifact.write", "artifact.load", "artifact.search"])
def test_artifact_tools_reject_unsafe_run_id_before_access(tmp_path, tool_name) -> None:
    manager = ArtifactManager(tmp_path)
    registry = ToolRegistry()
    register_artifact_tools(
        registry,
        artifact_manager=manager,
        execution_identity=_identity("run:stream"),
    )
    executor = ToolExecutor(registry, graph_identity=_identity("run:stream"))
    arguments = {"path_prefix": ""} if tool_name == "artifact.search" else {"path": "out.json"}
    if tool_name == "artifact.write":
        arguments["content"] = {"ok": True}

    result = _execute(executor, tool_name, arguments)

    assert result.status == ToolStatus.FAILED
    assert result.error_type == "ArtifactPathError"
    assert list(tmp_path.iterdir()) == []


def test_artifact_load_rejects_symlink_escape(tmp_path) -> None:
    root = tmp_path / "runs"
    manager = ArtifactManager(root)
    run_dir = manager.start_run("run-1")
    outside = tmp_path / "outside.json"
    outside.write_text('{"secret": true}', encoding="utf-8")
    link = run_dir / "output.json"
    try:
        link.symlink_to(outside)
    except (OSError, NotImplementedError):
        pytest.skip("symlink creation is not available")

    result = _execute(_executor(manager, "run-1"), "artifact.load", {"path": "output.json"})

    assert result.status == ToolStatus.FAILED
    assert result.error_type == "ArtifactPathError"
    assert result.output is None


def test_artifact_search_rejects_symlink_file_before_reading(tmp_path) -> None:
    root = tmp_path / "runs"
    manager = ArtifactManager(root)
    run_dir = manager.start_run("run-1")
    outside = tmp_path / "outside.txt"
    outside.write_text("needle-secret", encoding="utf-8")
    link = run_dir / "linked.txt"
    try:
        link.symlink_to(outside)
    except (OSError, NotImplementedError):
        pytest.skip("symlink creation is not available")

    result = _execute(_executor(manager, "run-1"), "artifact.search", {"query": "needle"})

    assert result.status == ToolStatus.FAILED
    assert result.error_type == "ArtifactPathError"
    assert result.output is None


def _executor(manager, run_id) -> ToolExecutor:
    registry = ToolRegistry()
    identity = _identity(run_id)
    register_artifact_tools(
        registry,
        artifact_manager=manager,
        execution_identity=identity,
    )
    return ToolExecutor(registry, graph_identity=identity)


def _identity(run_id: str) -> GraphExecutionIdentity:
    return GraphExecutionIdentity(
        run_id=run_id,
        graph_id="graph.test",
        graph_version="v1",
        graph_ref="graph.test@v1",
        graph_checksum="sha256:" + "0" * 64,
        node_id="node.artifact",
        node_instance_id="instance.artifact",
        activity_id="activity.artifact",
        attempt=1,
    )


def _execute(executor: ToolExecutor, tool_name: str, arguments: dict):
    return executor.execute(
        ToolCall(tool_name=tool_name, arguments=arguments),
        ToolPolicy(require_explicit_allowlist=False, require_approval_for_side_effects=False),
    ).result
