import json

from core.framework.artifacts import ArtifactManager
from framework.tool import (
    ToolCall,
    ToolExecutor,
    ToolPolicy,
    ToolStatus,
    build_tool_catalog,
)
from infrastructure.tools import (
    build_builtin_dangerous_tool_registry,
    build_builtin_safe_tool_registry,
    build_builtin_tool_registry,
)


def test_builtin_tool_registry_defaults_to_safe_core_tools() -> None:
    registry = build_builtin_tool_registry()
    names = {definition.name for definition in registry.list_tools()}

    assert "control.set_output" in names
    assert "control.report_progress" in names
    assert "source.parse_rss" not in names
    assert "source.extract_items" not in names
    assert "report.validate" not in names
    assert "quality.duplicate_check" not in names
    assert "arxiv.search_papers" not in names
    assert "github.fetch_releases" not in names
    assert "web.search" not in names
    assert "source.fetch_url" not in names
    assert "report.publish" not in names
    assert "artifact.load" not in names


def test_builtin_safe_registry_filters_dependency_backed_file_write_tools(tmp_path) -> None:
    artifact_manager = ArtifactManager(tmp_path)
    artifact_manager.start_run("run-tools")

    registry = build_builtin_safe_tool_registry(
        artifact_manager=artifact_manager,
        run_id="run-tools",
    )
    names = {definition.name for definition in registry.list_tools()}

    assert {"artifact.load", "artifact.search"}.issubset(names)
    assert "artifact.write" not in names


def test_builtin_dangerous_registry_collects_explicit_risky_tools(tmp_path) -> None:
    artifact_manager = ArtifactManager(tmp_path)
    artifact_manager.start_run("run-tools")

    registry = build_builtin_dangerous_tool_registry(
        artifact_manager=artifact_manager,
        run_id="run-tools",
        local_json_root=tmp_path / "local-json",
        vector_store=object(),
        qdrant_vector_store=object(),
        qdrant_document_store=object(),
        notification_options={
            "allowed_webhook_domains": ["example.com"],
            "rss_feed_path": tmp_path / "feed.xml",
        },
    )
    names = {definition.name for definition in registry.list_tools()}

    assert registry.validate_no_conflicts().ok is True
    assert {
        "artifact.write",
        "local_json.save",
        "memory.write",
        "notification.rss_publish",
        "notification.webhook",
        "qdrant.upsert",
        "web.search",
    }.issubset(names)
    assert "report.validate" not in names
    assert "quality.duplicate_check" not in names


def test_tool_catalog_applies_policy_and_groups_namespaces() -> None:
    registry = build_builtin_tool_registry()
    catalog = build_tool_catalog(
        registry,
        agent_id="analyst",
        policy=ToolPolicy(
            allowed_tools=["report.validate", "web.search", "quality.duplicate_check"],
            blocked_tools=["web.search"],
        ),
    )
    payload = catalog.to_dict()

    assert catalog.registry_valid is True
    assert [tool.name for tool in catalog.tools] == []
    assert payload["agent_id"] == "analyst"
    assert payload["tool_count"] == 0
    assert payload["namespaces"] == []


def test_builtin_registry_executes_real_control_tool() -> None:
    registry = build_builtin_tool_registry(include_network_tools=False)
    executor = ToolExecutor(registry)

    observation = executor.execute(
        ToolCall(
            tool_name="control.report_progress",
            arguments={
                "message": "working",
                "percent": 25,
                "metadata": {"step": "collect"},
            },
        ),
        ToolPolicy(allowed_tools=["control.report_progress"]),
    )

    assert observation.status == ToolStatus.SUCCEEDED
    assert observation.result.output == {
        "control_action": "report_progress",
        "message": "working",
        "percent": 25.0,
        "metadata": {"step": "collect"},
    }


def test_tool_catalog_payload_is_json_safe() -> None:
    payload = build_tool_catalog(build_builtin_tool_registry()).to_dict()

    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True)

    assert "control.set_output" in encoded
