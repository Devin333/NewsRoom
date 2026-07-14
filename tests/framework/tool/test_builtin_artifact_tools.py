from __future__ import annotations

import pytest

from framework.artifacts import ArtifactManager
from framework.tool import ToolCall, ToolExecutor, ToolPolicy, ToolRegistry, ToolStatus
from framework.tool.builtin.artifact import register_artifact_tools


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
    register_artifact_tools(registry, artifact_manager=manager, run_id="run:stream")
    executor = ToolExecutor(registry)
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
    register_artifact_tools(registry, artifact_manager=manager, run_id=run_id)
    return ToolExecutor(registry)


def _execute(executor: ToolExecutor, tool_name: str, arguments: dict):
    return executor.execute(
        ToolCall(tool_name=tool_name, arguments=arguments),
        ToolPolicy(require_explicit_allowlist=False, require_approval_for_side_effects=False),
    ).result
