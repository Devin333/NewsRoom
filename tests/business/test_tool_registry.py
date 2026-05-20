from business.tools import (
    build_business_dangerous_tool_registry,
    build_business_tool_registry,
)
from framework.artifacts import ArtifactManager
from framework.tool import ToolCall, ToolExecutor, ToolPolicy, ToolStatus, build_tool_catalog


def test_business_tool_registry_includes_safe_business_tools() -> None:
    registry = build_business_tool_registry()
    names = {definition.name for definition in registry.list_tools()}

    assert "control.set_output" in names
    assert "source.parse_rss" in names
    assert "source.extract_items" in names
    assert "report.validate" in names
    assert "quality.duplicate_check" in names
    assert "arxiv.search_papers" not in names
    assert "github.fetch_releases" not in names
    assert "source.fetch_url" not in names
    assert "report.publish" not in names


def test_business_dangerous_registry_includes_risky_business_tools(tmp_path) -> None:
    artifact_manager = ArtifactManager(tmp_path)
    artifact_manager.start_run("run-tools")

    registry = build_business_dangerous_tool_registry(
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


def test_business_registry_executes_report_validation_tool() -> None:
    registry = build_business_tool_registry(include_network_tools=False)
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


def test_business_tool_catalog_groups_business_namespaces() -> None:
    registry = build_business_tool_registry()
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
