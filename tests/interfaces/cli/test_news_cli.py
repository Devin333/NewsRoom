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
