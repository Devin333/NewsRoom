import json

from core.framework.artifacts import ArtifactManager
from core.framework.tools import (
    ToolCall,
    ToolExecutor,
    ToolPolicy,
    ToolStatus,
    build_builtin_dangerous_tool_registry,
    build_builtin_safe_tool_registry,
    build_builtin_tool_registry,
    build_tool_catalog,
)


def test_builtin_tool_registry_defaults_to_safe_core_tools() -> None:
    registry = build_builtin_tool_registry()
    names = {definition.name for definition in registry.list_tools()}

    assert "source.parse_rss" in names
    assert "source.extract_items" in names
    assert "report.validate" in names
    assert "quality.duplicate_check" in names
    assert "control.set_output" in names
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
        memory_ingestion_service=object(),
        qdrant_vector_store=object(),
        qdrant_document_store=object(),
        persistence_repository=object(),
        postgres_repository=object(),
        notification_options={
            "allowed_webhook_domains": ["example.com"],
            "rss_feed_path": tmp_path / "feed.xml",
        },
    )
    names = {definition.name for definition in registry.list_tools()}

    assert registry.validate_no_conflicts().ok is True
    assert {
        "artifact.write",
        "arxiv.search_papers",
        "github.fetch_releases",
        "local_json.save",
        "memory.index",
        "notification.rss_publish",
        "notification.webhook",
        "postgres.save_report",
        "qdrant.upsert",
        "report.export",
        "report.publish",
        "source.fetch_url",
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
    assert [tool.name for tool in catalog.tools] == [
        "quality.duplicate_check",
        "report.validate",
    ]
    assert payload["agent_id"] == "analyst"
    assert payload["tool_count"] == 2
    assert payload["namespaces"] == [
        {"namespace": "quality", "tool_count": 1},
        {"namespace": "report", "tool_count": 1},
    ]


def test_builtin_registry_executes_real_report_validation_tool() -> None:
    registry = build_builtin_tool_registry(include_network_tools=False)
    executor = ToolExecutor(registry)

    observation = executor.execute(
        ToolCall(
            tool_name="report.validate",
            arguments={
                "report": {
                    "title": "Daily Brief",
                    "sections": [{"title": "Summary", "body": "Supported update"}],
                    "source_urls": ["https://example.com/source"],
                }
            },
        ),
        ToolPolicy(allowed_tools=["report.validate"]),
    )

    assert observation.status == ToolStatus.SUCCEEDED
    assert observation.result.output == {
        "valid": True,
        "errors": [],
        "section_count": 1,
        "source_url_count": 1,
    }


def test_tool_catalog_payload_is_json_safe() -> None:
    payload = build_tool_catalog(build_builtin_tool_registry()).to_dict()

    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True)

    assert "source.parse_rss" in encoded
