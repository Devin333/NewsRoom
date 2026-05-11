import json

from interfaces.cli.news import main


def test_news_cli_entities_create_list_and_match_reports_json(tmp_path, capsys) -> None:
    store_path = tmp_path / "entities.json"
    artifact_root = tmp_path / "runs"

    create_code = main(
        [
            "entities",
            "create",
            "--name",
            "OpenAI",
            "--entity-id",
            "company:openai",
            "--alias",
            "ChatGPT",
            "--store-path",
            str(store_path),
            "--json",
        ]
    )
    create_payload = json.loads(capsys.readouterr().out)
    assert create_code == 0
    assert create_payload["entity_id"] == "company:openai"

    assert (
        main(
            [
                "run",
                "daily",
                "--profile",
                "live-offline",
                "--topic",
                "OpenAI policy",
                "--artifact-root",
                str(artifact_root),
                "--run-id",
                "entity-daily",
            ]
        )
        == 0
    )
    capsys.readouterr()

    list_code = main(["entities", "list", "--store-path", str(store_path), "--json"])
    list_payload = json.loads(capsys.readouterr().out)
    assert list_code == 0
    assert list_payload["entity_count"] == 1

    match_code = main(
        [
            "entities",
            "match-reports",
            "company:openai",
            "--store-path",
            str(store_path),
            "--artifact-root",
            str(artifact_root),
            "--workflow-id",
            "daily-intelligence-live",
            "--json",
        ]
    )
    match_payload = json.loads(capsys.readouterr().out)

    assert match_code == 0
    assert match_payload["match_count"] == 1
    assert match_payload["matches"][0]["report_id"] == "entity-daily:final"


def test_news_cli_entities_disable_enable_delete_json(tmp_path, capsys) -> None:
    store_path = tmp_path / "entities.json"
    assert (
        main(
            [
                "entities",
                "create",
                "--name",
                "OpenAI",
                "--entity-id",
                "company:openai",
                "--store-path",
                str(store_path),
                "--json",
            ]
        )
        == 0
    )
    capsys.readouterr()

    disable_code = main(["entities", "disable", "company:openai", "--store-path", str(store_path), "--json"])
    disable_payload = json.loads(capsys.readouterr().out)
    enable_code = main(["entities", "enable", "company:openai", "--store-path", str(store_path), "--json"])
    enable_payload = json.loads(capsys.readouterr().out)
    delete_code = main(["entities", "delete", "company:openai", "--store-path", str(store_path), "--json"])
    delete_payload = json.loads(capsys.readouterr().out)

    assert disable_code == 0
    assert disable_payload["enabled"] is False
    assert enable_code == 0
    assert enable_payload["enabled"] is True
    assert delete_code == 0
    assert delete_payload == {"deleted": True, "entity_id": "company:openai"}


def test_news_cli_entities_rejects_secret_metadata(tmp_path, capsys) -> None:
    exit_code = main(
        [
            "entities",
            "create",
            "--name",
            "OpenAI",
            "--metadata",
            "api_key=hidden",
            "--store-path",
            str(tmp_path / "entities.json"),
        ]
    )
    captured = capsys.readouterr()

    assert exit_code == 1
    assert "secret-like key" in captured.out
