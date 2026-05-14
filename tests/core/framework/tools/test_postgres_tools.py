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
            allow_dangerous_tools=True,
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
            allow_dangerous_tools=True,
            require_approval_for_side_effects=False,
        ),
    )

    assert observation.status == ToolStatus.SUCCEEDED
    assert observation.result.output["tool_name"] == "postgres.insert_report"
    assert repository.records[0].report_id == "run-1:final"


def test_postgres_save_report_tool_is_blocked_by_default() -> None:
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

    assert observation.status == ToolStatus.BLOCKED
    assert repository.records == []


def test_postgres_update_source_health_tool_writes_typed_health_record() -> None:
    repository = _RecordingReportRepository()
    registry = ToolRegistry()
    register_postgres_tools(
        registry,
        repository=repository,
        source_health_repository=repository,
    )
    executor = ToolExecutor(registry)

    observation = executor.execute(
        ToolCall(
            tool_name="postgres.update_source_health",
            arguments={
                "source_id": "rss-example",
                "status": "degraded",
                "consecutive_failures": 1,
                "success_count_24h": 2,
                "failure_count_24h": 1,
                "avg_latency_ms_24h": 123.5,
                "last_failure_at": "2026-05-12T00:00:00Z",
                "last_error": {
                    "error_type": "fetch_timeout",
                    "error_message": "timed out",
                    "url": "https://example.com/feed.xml",
                    "metadata": {"phase": "fetch"},
                },
            },
        ),
        ToolPolicy(
            allowed_tools=["postgres.update_source_health"],
            allow_dangerous_tools=True,
            require_approval_for_side_effects=False,
        ),
    )

    health = repository.health_records[0]

    assert observation.status == ToolStatus.SUCCEEDED
    assert observation.result.output == {
        "updated": True,
        "source_id": "rss-example",
        "status": "degraded",
        "consecutive_failures": 1,
        "success_count_24h": 2,
        "failure_count_24h": 1,
        "avg_latency_ms_24h": 123.5,
        "has_last_error": True,
    }
    assert health.source_id == "rss-example"
    assert health.status.value == "degraded"
    assert health.success_count_24h == 2
    assert health.failure_count_24h == 1
    assert health.avg_latency_ms_24h == 123.5
    assert health.last_error.error_type == "fetch_timeout"
    assert health.last_error.metadata == {"phase": "fetch"}


def test_postgres_update_source_health_tool_is_blocked_by_default() -> None:
    repository = _RecordingReportRepository()
    registry = ToolRegistry()
    register_postgres_tools(
        registry,
        repository=repository,
        source_health_repository=repository,
    )
    executor = ToolExecutor(registry)

    observation = executor.execute(
        ToolCall(
            tool_name="postgres.update_source_health",
            arguments={"source_id": "rss-example", "status": "healthy"},
        ),
        ToolPolicy(allowed_tools=["postgres.update_source_health"]),
    )

    assert observation.status == ToolStatus.BLOCKED
    assert repository.health_records == []


class _RecordingReportRepository:
    def __init__(self) -> None:
        self.records = []
        self.health_records = []

    def save_report(self, record):
        self.records.append(record)

    def update_source_health(self, health):
        self.health_records.append(health)
