import json

from core.framework.artifacts import ArtifactManager
from core.framework.tools import (
    REDACTED_VALUE,
    ToolCall,
    ToolDefinition,
    ToolPolicy,
    ToolRegistry,
    ToolStatus,
    ToolTestCase,
    ToolTestRunner,
    build_builtin_dangerous_tool_registry,
    build_builtin_safe_tool_registry,
)


def test_tool_test_runner_uses_real_executor_and_artifact_spill(tmp_path) -> None:
    registry = ToolRegistry()
    registry.register(
        ToolDefinition(name="memory.large", input_schema={"required": ["query"]}),
        lambda args: {
            "items": [{"title": args["query"], "body": "x" * 80}],
            "token": "hidden-token",
        },
    )
    artifact_manager = ArtifactManager(tmp_path)
    artifact_manager.start_run("tool-test-run")
    runner = ToolTestRunner(
        registry,
        artifact_manager=artifact_manager,
        run_id="tool-test-run",
    )

    report = runner.run_case(
        ToolTestCase(
            name="large memory search spills",
            call=ToolCall(
                tool_name="memory.large",
                arguments={"query": "chips"},
                call_id="tool-test-call",
            ),
            policy=ToolPolicy(allowed_tools=["memory.large"], max_result_chars_inline=20),
            expected_status=ToolStatus.SUCCEEDED,
            require_artifact_refs=True,
        )
    )

    payload = report.to_dict()
    artifact_ref = payload["observation"]["result"]["artifact_refs"][0]
    artifact_path = tmp_path / "tool-test-run" / artifact_ref["relative_path"]
    artifact_payload = json.loads(artifact_path.read_text(encoding="utf-8"))

    assert report.passed is True
    assert artifact_path.exists()
    assert artifact_payload["output"]["token"] == REDACTED_VALUE
    assert report.metrics.spilled_result_count == 1
    assert "tool_result_spilled" in [event.event_type for event in report.events]
    assert "hidden-token" not in str(payload)


def test_tool_test_runner_reports_status_expectation_errors() -> None:
    registry = ToolRegistry()
    registry.register(ToolDefinition(name="memory.search"), lambda args: {"ok": True})
    runner = ToolTestRunner(registry)

    report = runner.run_case(
        ToolTestCase(
            name="blocked tool expected success",
            call=ToolCall(tool_name="memory.search", arguments={}),
            policy=ToolPolicy(allowed_tools=[]),
            expected_status=ToolStatus.SUCCEEDED,
        )
    )

    assert report.passed is False
    assert report.observation.status == ToolStatus.BLOCKED
    assert report.errors == ["expected status succeeded, got blocked"]
    assert report.metrics.blocked_calls == 1


def test_tool_test_runner_dry_run_blocks_default_dangerous_named_tool() -> None:
    registry = ToolRegistry()
    registry.register(ToolDefinition(name="http.request"), lambda args: {"sent": True})
    runner = ToolTestRunner(registry)

    report = runner.run_case(
        ToolTestCase(
            name="http request dry run blocked",
            tool_name="http.request",
            policy=ToolPolicy(allowed_tools=["http.request"]),
            expected_status=ToolStatus.BLOCKED,
            expected_error_type="ToolPermissionError",
            dry_run=True,
        )
    )

    assert report.passed is True
    assert report.observation.result.error_message == "dangerous tool is not allowed: http.request"


def test_tool_test_runner_dry_run_enforces_restricted_agent_boundary() -> None:
    registry = ToolRegistry()
    registry.register(ToolDefinition(name="source.fetch_url"), lambda args: {"body": "ok"})
    runner = ToolTestRunner(registry)

    report = runner.run_case(
        ToolTestCase(
            name="writer fetch dry run blocked",
            tool_name="source.fetch_url",
            requested_by_agent_id="WriterAgent",
            policy=ToolPolicy(allowed_tools=["source.fetch_url"]),
            expected_status=ToolStatus.BLOCKED,
            expected_error_type="ToolPermissionError",
            dry_run=True,
        )
    )

    assert report.passed is True
    assert "restricted agent" in (report.observation.result.error_message or "")


def test_tool_test_runner_runs_minimal_safe_registry_contract() -> None:
    registry = build_builtin_safe_tool_registry()
    runner = ToolTestRunner(registry)

    reports = runner.run_cases(
        [
            ToolTestCase(
                name="safe report validate",
                tool_name="report.validate",
                args={
                    "report": {
                        "title": "Daily Brief",
                        "sections": [{"title": "Summary", "body": "Supported update"}],
                        "source_urls": ["https://example.com/source"],
                    }
                },
                policy=ToolPolicy(allowed_tools=["report.validate"]),
                expected_status=ToolStatus.SUCCEEDED,
                expected_output_keys=[
                    "valid",
                    "errors",
                    "section_count",
                    "source_url_count",
                ],
            )
        ]
    )

    assert [report.passed for report in reports] == [True]
    assert reports[0].observation.result.output["valid"] is True


def test_tool_test_runner_runs_minimal_dangerous_registry_default_deny_contract(
    tmp_path,
) -> None:
    artifact_manager = ArtifactManager(tmp_path)
    artifact_manager.start_run("dangerous-registry-test")
    registry = build_builtin_dangerous_tool_registry(
        artifact_manager=artifact_manager,
        run_id="dangerous-registry-test",
        notification_options={"allowed_webhook_domains": ["example.com"]},
    )
    runner = ToolTestRunner(registry)

    reports = runner.run_cases(
        [
            ToolTestCase(
                name="dangerous webhook default deny",
                tool_name="notification.webhook",
                args={
                    "url": "https://example.com/hook",
                    "payload": {"ok": True},
                },
                policy=ToolPolicy(allowed_tools=["notification.webhook"]),
                expected_status=ToolStatus.BLOCKED,
                expected_error_type="ToolPermissionError",
            )
        ]
    )

    assert [report.passed for report in reports] == [True]
    assert reports[0].observation.result.error_message == (
        "dangerous tool is not allowed: notification.webhook"
    )
