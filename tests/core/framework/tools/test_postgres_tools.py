from core.framework.tools import (
    ToolCall,
    ToolExecutor,
    ToolPolicy,
    ToolRegistry,
    ToolStatus,
    register_postgres_tools,
)


def test_postgres_save_report_tool_writes_typed_report_record() -> None:
    repository = _RecordingReportRepository()
    registry = ToolRegistry()
    register_postgres_tools(registry, repository=repository)
    executor = ToolExecutor(registry)

    observation = executor.execute(
        ToolCall(
            tool_name="postgres.save_report",
            arguments={
                "report_id": "run-1:final",
                "run_id": "run-1",
                "status": "final",
                "title": "Daily Report",
                "report_json": {"title": "Daily Report"},
                "report_markdown": "# Daily Report",
                "quality_score": 0.91,
                "citation_coverage_score": 1.0,
                "manifest_path": ".newsroom/runs/run-1/manifest.json",
            },
        ),
        ToolPolicy(
            allowed_tools=["postgres.save_report"],
            require_approval_for_side_effects=False,
        ),
    )

    record = repository.records[0]

    assert observation.status == ToolStatus.SUCCEEDED
    assert observation.result.output == {
        "saved": True,
        "tool_name": "postgres.save_report",
        "report_id": "run-1:final",
        "run_id": "run-1",
        "status": "final",
        "title": "Daily Report",
    }
    assert record.report_id == "run-1:final"
    assert record.report_json == {"title": "Daily Report"}
    assert record.report_markdown == "# Daily Report"
    assert record.quality_score == 0.91
    assert record.citation_coverage_score == 1.0


def test_postgres_insert_report_alias_uses_same_repository_path() -> None:
    repository = _RecordingReportRepository()
    registry = ToolRegistry()
    register_postgres_tools(registry, repository=repository)
    executor = ToolExecutor(registry)

    observation = executor.execute(
        ToolCall(
            tool_name="postgres.insert_report",
            arguments={
                "report_id": "run-1:final",
                "run_id": "run-1",
                "status": "final",
                "report_json": {"title": "Daily Report"},
            },
        ),
        ToolPolicy(
            allowed_tools=["postgres.insert_report"],
            require_approval_for_side_effects=False,
        ),
    )

    assert observation.status == ToolStatus.SUCCEEDED
    assert observation.result.output["tool_name"] == "postgres.insert_report"
    assert repository.records[0].report_id == "run-1:final"


def test_postgres_save_report_tool_requires_approval_by_default() -> None:
    repository = _RecordingReportRepository()
    registry = ToolRegistry()
    register_postgres_tools(registry, repository=repository)
    executor = ToolExecutor(registry)

    observation = executor.execute(
        ToolCall(
            tool_name="postgres.save_report",
            arguments={
                "report_id": "run-1:final",
                "run_id": "run-1",
                "status": "final",
                "report_json": {"title": "Daily Report"},
            },
        ),
        ToolPolicy(allowed_tools=["postgres.save_report"]),
    )

    assert observation.status == ToolStatus.APPROVAL_REQUIRED
    assert repository.records == []


class _RecordingReportRepository:
    def __init__(self) -> None:
        self.records = []

    def save_report(self, record):
        self.records.append(record)
