import json

from interfaces.cli.news import main


def test_news_cli_run_test_no_llm_json_output(tmp_path, capsys) -> None:
    exit_code = main(
        [
            "dev",
            "run-test-no-llm",
            "--artifact-root",
            str(tmp_path),
            "--run-id",
            "cli-success",
            "--topic",
            "chips",
            "--json",
        ]
    )

    captured = capsys.readouterr()
    payload = json.loads(captured.out)

    assert exit_code == 0
    assert payload["status"] == "succeeded"
    assert payload["run_id"] == "cli-success"
    assert payload["output"]["final_report"]["topic"] == "chips"


def test_news_cli_run_test_no_llm_human_output(tmp_path, capsys) -> None:
    exit_code = main(
        [
            "dev",
            "run-test-no-llm",
            "--artifact-root",
            str(tmp_path),
            "--run-id",
            "cli-human",
        ]
    )

    captured = capsys.readouterr()

    assert exit_code == 0
    assert "status=succeeded" in captured.out
    assert "run_id=cli-human" in captured.out


def test_news_cli_run_test_agent_loop_json_output(tmp_path, capsys) -> None:
    exit_code = main(
        [
            "dev",
            "run-test-agent-loop",
            "--artifact-root",
            str(tmp_path),
            "--run-id",
            "cli-agent-loop",
            "--topic",
            "chips",
            "--json",
        ]
    )

    captured = capsys.readouterr()
    payload = json.loads(captured.out)

    assert exit_code == 0
    assert payload["status"] == "succeeded"
    assert payload["run_id"] == "cli-agent-loop"
    assert payload["output"]["agent_loop_metrics"]["llm_calls"] == 3
    assert payload["output"]["agent_loop_metrics"]["tool_calls"] == 1


def test_news_cli_run_test_agent_loop_human_output(tmp_path, capsys) -> None:
    exit_code = main(
        [
            "dev",
            "run-test-agent-loop",
            "--artifact-root",
            str(tmp_path),
            "--run-id",
            "cli-agent-loop-human",
        ]
    )

    captured = capsys.readouterr()

    assert exit_code == 0
    assert "status=succeeded" in captured.out
    assert "run_id=cli-agent-loop-human" in captured.out
    assert "llm_calls=3" in captured.out
    assert "tool_calls=1" in captured.out


def test_news_cli_run_daily_live_offline_json_output(tmp_path, capsys) -> None:
    exit_code = main(
        [
            "run",
            "daily",
            "--profile",
            "live-offline",
            "--artifact-root",
            str(tmp_path),
            "--run-id",
            "cli-daily-offline",
            "--topic",
            "AI policy",
            "--source-limit",
            "2",
            "--json",
        ]
    )

    captured = capsys.readouterr()
    payload = json.loads(captured.out)

    assert exit_code == 0
    assert payload["status"] == "succeeded"
    assert payload["run_id"] == "cli-daily-offline"
    assert payload["output"]["final_report"]["title"] == "Daily Intelligence: AI policy"


def test_run_service_persists_daily_result(tmp_path, monkeypatch) -> None:
    from interfaces.services.run_service import RunApplicationService
    import interfaces.services.run_service as run_service_module

    fake_repository = _FakePersistenceRepository()
    monkeypatch.setattr(
        run_service_module,
        "repository_from_env",
        lambda artifact_root: fake_repository,
    )

    result = RunApplicationService(artifact_root=tmp_path).run_daily(
        profile="live-offline",
        topic="AI policy",
        source_limit=1,
        run_id="persisted-daily",
    )

    assert result.run_id == "persisted-daily"
    assert fake_repository.migrated is True
    assert fake_repository.workflow_runs[0].run_id == "persisted-daily"
    assert fake_repository.reports[0].status == "final"


def test_news_cli_run_daily_live_offline_human_output(tmp_path, capsys) -> None:
    exit_code = main(
        [
            "run",
            "daily",
            "--profile",
            "live-offline",
            "--artifact-root",
            str(tmp_path),
            "--run-id",
            "cli-daily-human",
        ]
    )

    captured = capsys.readouterr()

    assert exit_code == 0
    assert "status=succeeded" in captured.out
    assert "profile=live-offline" in captured.out
    assert "run_id=cli-daily-human" in captured.out


def test_news_cli_run_weekly_json_output_from_daily_artifacts(tmp_path, capsys) -> None:
    assert (
        main(
            [
                "run",
                "daily",
                "--profile",
                "live-offline",
                "--artifact-root",
                str(tmp_path),
                "--run-id",
                "weekly-cli-daily",
                "--topic",
                "AI policy",
            ]
        )
        == 0
    )
    capsys.readouterr()

    exit_code = main(
        [
            "run",
            "weekly",
            "--artifact-root",
            str(tmp_path),
            "--run-id",
            "weekly-cli",
            "--topic",
            "AI policy",
            "--period-start",
            "2026-05-01T00:00:00Z",
            "--period-end",
            "2026-05-20T00:00:00Z",
            "--json",
        ]
    )

    captured = capsys.readouterr()
    payload = json.loads(captured.out)

    assert exit_code == 0
    assert payload["status"] == "succeeded"
    assert payload["run_id"] == "weekly-cli"
    assert payload["workflow_id"] == "weekly-intelligence"
    assert payload["output"]["weekly_metrics"]["source_report_count"] == 1
    assert payload["output"]["final_report"]["metadata"]["source_report_ids"] == [
        "weekly-cli-daily:final"
    ]


def test_news_cli_latest_markdown_output(tmp_path, capsys) -> None:
    assert (
        main(
            [
                "run",
                "daily",
                "--profile",
                "live-offline",
                "--artifact-root",
                str(tmp_path),
                "--run-id",
                "latest-source",
            ]
        )
        == 0
    )
    capsys.readouterr()

    exit_code = main(["latest", "--artifact-root", str(tmp_path), "--format", "markdown"])
    captured = capsys.readouterr()

    assert exit_code == 0
    assert "# Daily Intelligence:" in captured.out


def test_news_cli_latest_json_output(tmp_path, capsys) -> None:
    assert (
        main(
            [
                "run",
                "daily",
                "--profile",
                "live-offline",
                "--artifact-root",
                str(tmp_path),
                "--run-id",
                "latest-json-source",
            ]
        )
        == 0
    )
    capsys.readouterr()

    exit_code = main(["latest", "--artifact-root", str(tmp_path), "--format", "json"])
    captured = capsys.readouterr()
    payload = json.loads(captured.out)

    assert exit_code == 0
    assert payload["run_id"] == "latest-json-source"
    assert payload["status"] == "final"
    assert payload["report_json"]["title"].startswith("Daily Intelligence:")


def test_news_cli_latest_missing_report(tmp_path, capsys) -> None:
    exit_code = main(["latest", "--artifact-root", str(tmp_path)])
    captured = capsys.readouterr()

    assert exit_code == 1
    assert "no local report" in captured.out


def test_news_cli_reports_search_json_output(tmp_path, capsys) -> None:
    assert (
        main(
            [
                "run",
                "daily",
                "--profile",
                "live-offline",
                "--artifact-root",
                str(tmp_path),
                "--run-id",
                "search-source",
                "--topic",
                "AI policy",
            ]
        )
        == 0
    )
    capsys.readouterr()

    exit_code = main(["reports", "search", "policy", "--artifact-root", str(tmp_path), "--json"])
    captured = capsys.readouterr()
    payload = json.loads(captured.out)

    assert exit_code == 0
    assert payload["query"] == "policy"
    assert payload["report_count"] == 1
    assert payload["reports"][0]["run_id"] == "search-source"
    assert payload["reports"][0]["report_id"] == "search-source:final"
    assert payload["reports"][0]["status"] == "final"


def test_news_cli_reports_list_json_output(tmp_path, capsys) -> None:
    assert (
        main(
            [
                "run",
                "daily",
                "--profile",
                "live-offline",
                "--artifact-root",
                str(tmp_path),
                "--run-id",
                "list-source",
                "--topic",
                "AI policy",
            ]
        )
        == 0
    )
    capsys.readouterr()

    exit_code = main(
        [
            "reports",
            "list",
            "--workflow-id",
            "daily-intelligence-live",
            "--artifact-root",
            str(tmp_path),
            "--json",
        ]
    )
    captured = capsys.readouterr()
    payload = json.loads(captured.out)

    assert exit_code == 0
    assert payload["workflow_id"] == "daily-intelligence-live"
    assert payload["report_count"] == 1
    assert payload["reports"][0]["report_id"] == "list-source:final"
    assert payload["reports"][0]["workflow_id"] == "daily-intelligence-live"


def test_news_cli_reports_show_json_output(tmp_path, capsys) -> None:
    assert (
        main(
            [
                "run",
                "daily",
                "--profile",
                "live-offline",
                "--artifact-root",
                str(tmp_path),
                "--run-id",
                "show-source",
                "--topic",
                "AI policy",
            ]
        )
        == 0
    )
    capsys.readouterr()

    exit_code = main(
        [
            "reports",
            "show",
            "show-source:final",
            "--artifact-root",
            str(tmp_path),
            "--format",
            "json",
        ]
    )
    captured = capsys.readouterr()
    payload = json.loads(captured.out)

    assert exit_code == 0
    assert payload["report_id"] == "show-source:final"
    assert payload["run_id"] == "show-source"
    assert payload["status"] == "final"
    assert payload["report_json"]["title"] == "Daily Intelligence: AI policy"


class _FakePersistenceRepository:
    def __init__(self) -> None:
        self.migrated = False
        self.workflow_runs = []
        self.reports = []

    def migrate(self) -> None:
        self.migrated = True

    def save_workflow_run(self, record) -> None:
        self.workflow_runs.append(record)

    def save_report(self, record) -> None:
        self.reports.append(record)
