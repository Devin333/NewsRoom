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
