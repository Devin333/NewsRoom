import json

from core.framework.artifacts import ArtifactManager
from framework.tool import (
    ToolCall,
    ToolExecutor,
    ToolPolicy,
    ToolRegistry,
    ToolStatus,
)
from business.layers.output.tools import register_report_tools
from interfaces.services.report_service import ReportApplicationService
from storage.repository import LocalJsonPersistenceAdapter


def test_report_tools_render_markdown_and_json_through_executor() -> None:
    registry = ToolRegistry()
    register_report_tools(registry)
    executor = ToolExecutor(registry)
    report = {
        "title": "Daily Report",
        "sections": [{"title": "Summary", "content": "All systems nominal."}],
        "source_urls": ["https://example.com/source"],
        "metadata": {"profile": "test"},
    }

    markdown_observation = executor.execute(
        ToolCall(tool_name="report.render_markdown", arguments={"report": report}),
        ToolPolicy(allowed_tools=["report.render_markdown"]),
    )
    json_observation = executor.execute(
        ToolCall(tool_name="report.render_json", arguments={"report": report}),
        ToolPolicy(allowed_tools=["report.render_json"]),
    )

    assert markdown_observation.status == ToolStatus.SUCCEEDED
    assert "# Daily Report" in markdown_observation.result.output["markdown"]
    assert "- https://example.com/source" in markdown_observation.result.output["markdown"]
    assert json_observation.status == ToolStatus.SUCCEEDED
    assert json_observation.result.output["report"]["title"] == "Daily Report"
    assert json_observation.result.output["report"]["metadata"] == {"profile": "test"}


def test_report_tool_rejects_invalid_report_payload() -> None:
    registry = ToolRegistry()
    register_report_tools(registry)
    executor = ToolExecutor(registry)

    observation = executor.execute(
        ToolCall(tool_name="report.render_markdown", arguments={"report": {"sections": []}}),
        ToolPolicy(allowed_tools=["report.render_markdown"]),
    )

    assert observation.status == ToolStatus.FAILED
    assert observation.result.error_type == "ValueError"
    assert "report.title is required" in (observation.result.error_message or "")


def test_report_validate_tool_returns_structured_valid_result() -> None:
    registry = ToolRegistry()
    register_report_tools(registry)
    executor = ToolExecutor(registry)
    report = {
        "title": "Daily Report",
        "sections": [{"title": "Summary", "content": "All systems nominal."}],
        "source_urls": ["https://example.com/source"],
        "metadata": {"profile": "test"},
    }

    observation = executor.execute(
        ToolCall(tool_name="report.validate", arguments={"report": report}),
        ToolPolicy(allowed_tools=["report.validate"]),
    )

    assert observation.status == ToolStatus.SUCCEEDED
    assert observation.result.output == {
        "valid": True,
        "errors": [],
        "section_count": 1,
        "source_url_count": 1,
    }


def test_report_validate_tool_returns_structured_errors_for_invalid_report() -> None:
    registry = ToolRegistry()
    register_report_tools(registry)
    executor = ToolExecutor(registry)

    observation = executor.execute(
        ToolCall(tool_name="report.validate", arguments={"report": {"sections": []}}),
        ToolPolicy(allowed_tools=["report.validate"]),
    )

    assert observation.status == ToolStatus.SUCCEEDED
    assert observation.result.output["valid"] is False
    assert observation.result.output["errors"] == ["report.title is required"]


def test_report_search_tool_returns_persisted_report_summaries(tmp_path) -> None:
    _write_report_run(tmp_path, "run-1", "2026-05-11T00:00:00Z", "AI Policy Report")
    _write_report_run(tmp_path, "run-2", "2026-05-12T00:00:00Z", "Chip Supply Report")
    registry = ToolRegistry()
    register_report_tools(
        registry,
        report_service=ReportApplicationService(artifact_root=tmp_path),
    )
    executor = ToolExecutor(registry)

    observation = executor.execute(
        ToolCall(
            tool_name="report.search",
            arguments={"query": "policy", "limit": 10},
        ),
        ToolPolicy(allowed_tools=["report.search"]),
    )

    report = observation.result.output["reports"][0]

    assert observation.status == ToolStatus.SUCCEEDED
    assert observation.result.output["query"] == "policy"
    assert observation.result.output["report_count"] == 1
    assert report["report_id"] == "run-1:final"
    assert report["title"] == "AI Policy Report"
    assert "report_json" not in report
    assert "report_markdown" not in report


def test_report_search_tool_rejects_blank_query() -> None:
    registry = ToolRegistry()
    register_report_tools(registry, report_service=_FailingReportService())
    executor = ToolExecutor(registry)

    observation = executor.execute(
        ToolCall(tool_name="report.search", arguments={"query": " "}),
        ToolPolicy(allowed_tools=["report.search"]),
    )

    assert observation.status == ToolStatus.FAILED
    assert "query is required" in (observation.result.error_message or "")


def test_report_export_tool_writes_markdown_and_json_artifacts(tmp_path) -> None:
    artifact_manager = ArtifactManager(tmp_path)
    artifact_manager.start_run("report-run")
    registry = ToolRegistry()
    register_report_tools(
        registry,
        artifact_manager=artifact_manager,
        run_id="report-run",
    )
    executor = ToolExecutor(registry)
    report = {
        "title": "Daily Report",
        "sections": [{"title": "Summary", "content": "All systems nominal."}],
        "source_urls": ["https://example.com/source"],
        "metadata": {"profile": "test"},
    }

    markdown_observation = executor.execute(
        ToolCall(
            tool_name="report.export",
            arguments={"report": report, "path": "exports/daily.md"},
        ),
        ToolPolicy(
            allowed_tools=["report.export"],
            require_approval_for_side_effects=False,
        ),
    )
    json_observation = executor.execute(
        ToolCall(
            tool_name="report.export",
            arguments={"report": report, "format": "json"},
        ),
        ToolPolicy(
            allowed_tools=["report.export"],
            require_approval_for_side_effects=False,
        ),
    )

    markdown_path = tmp_path / "report-run" / "exports" / "daily.md"
    json_path = tmp_path / "report-run" / "reports" / "daily-report.json"

    assert markdown_observation.status == ToolStatus.SUCCEEDED
    assert markdown_path.read_text(encoding="utf-8").startswith("# Daily Report")
    assert markdown_observation.result.output["relative_path"] == "exports/daily.md"
    assert markdown_observation.result.output["content_type"] == "text/markdown"
    assert json_observation.status == ToolStatus.SUCCEEDED
    assert json.loads(json_path.read_text(encoding="utf-8"))["title"] == "Daily Report"
    assert json_observation.result.output["relative_path"] == "reports/daily-report.json"
    assert json_observation.result.output["content_type"] == "application/json"


def test_report_publish_tool_saves_report_record(tmp_path) -> None:
    repository = LocalJsonPersistenceAdapter(tmp_path)
    registry = ToolRegistry()
    register_report_tools(registry, persistence_repository=repository)
    executor = ToolExecutor(registry)
    report = {
        "title": "Daily Report",
        "sections": [{"title": "Summary", "content": "All systems nominal."}],
        "source_urls": ["https://example.com/source"],
    }

    observation = executor.execute(
        ToolCall(
            tool_name="report.publish",
            arguments={
                "run_id": "run-1",
                "report": report,
                "quality_score": 0.91,
                "citation_coverage_score": 1.0,
            },
        ),
        ToolPolicy(
            allowed_tools=["report.publish"],
            allow_dangerous_tools=True,
            require_approval_for_side_effects=False,
        ),
    )

    record_path = tmp_path / "_records" / "reports" / "run-1_final.json"
    record = json.loads(record_path.read_text(encoding="utf-8"))

    assert observation.status == ToolStatus.SUCCEEDED
    assert observation.result.output == {
        "published": True,
        "report_id": "run-1:final",
        "run_id": "run-1",
        "status": "final",
        "title": "Daily Report",
        "repository": "LocalJsonPersistenceAdapter",
    }
    assert record["report_id"] == "run-1:final"
    assert record["report_json"]["title"] == "Daily Report"
    assert record["report_markdown"].startswith("# Daily Report")
    assert record["quality_score"] == 0.91
    assert record["citation_coverage_score"] == 1.0


def test_report_publish_tool_is_blocked_by_default(tmp_path) -> None:
    repository = LocalJsonPersistenceAdapter(tmp_path)
    registry = ToolRegistry()
    register_report_tools(registry, persistence_repository=repository)
    executor = ToolExecutor(registry)

    observation = executor.execute(
        ToolCall(
            tool_name="report.publish",
            arguments={
                "run_id": "run-1",
                "report": {
                    "title": "Daily Report",
                    "sections": [{"title": "Summary", "content": "Needs approval."}],
                },
            },
        ),
        ToolPolicy(allowed_tools=["report.publish"]),
    )

    assert observation.status == ToolStatus.APPROVAL_REQUIRED
    assert not (tmp_path / "_records" / "reports" / "run-1_final.json").exists()


def _write_report_run(root, run_id: str, finished_at: str, title: str) -> None:
    run_dir = root / run_id
    run_dir.mkdir(parents=True)
    (run_dir / "report.json").write_text(json.dumps({"title": title}), encoding="utf-8")
    (run_dir / "report.md").write_text(f"# {title}\n", encoding="utf-8")
    (run_dir / "manifest.json").write_text(
        json.dumps(
            {
                "run_id": run_id,
                "status": "succeeded",
                "finished_at": finished_at,
                "quality_score": 0.9,
                "artifacts": {
                    "report_json": "report.json",
                    "report_markdown": "report.md",
                },
            }
        ),
        encoding="utf-8",
    )


class _FailingReportService:
    def search_reports(self, *, query, limit):
        raise AssertionError("report service should not be called")
