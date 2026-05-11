import json

import interfaces.cli.news as news_cli


def test_news_cli_subscriptions_create_and_list_json(tmp_path, capsys) -> None:
    store_path = tmp_path / "subscriptions.json"

    create_code = news_cli.main(
        [
            "subscriptions",
            "create",
            "--topic",
            "AI policy",
            "--subscription-id",
            "weekly:ai-policy",
            "--cadence",
            "weekly",
            "--source-limit",
            "4",
            "--metadata",
            "region=global",
            "--store-path",
            str(store_path),
            "--json",
        ]
    )
    created = json.loads(capsys.readouterr().out)

    list_code = news_cli.main(["subscriptions", "list", "--store-path", str(store_path), "--json"])
    listed = json.loads(capsys.readouterr().out)

    assert create_code == 0
    assert created["subscription_id"] == "weekly:ai-policy"
    assert created["metadata"] == {"region": "global"}
    assert list_code == 0
    assert listed["subscription_count"] == 1
    assert listed["subscriptions"][0]["topic"] == "AI policy"


def test_news_cli_subscriptions_disable_enable_delete(tmp_path, capsys) -> None:
    store_path = tmp_path / "subscriptions.json"
    news_cli.main(
        [
            "subscriptions",
            "create",
            "--topic",
            "AI",
            "--subscription-id",
            "weekly:ai",
            "--store-path",
            str(store_path),
            "--json",
        ]
    )
    capsys.readouterr()

    disable_code = news_cli.main(["subscriptions", "disable", "weekly:ai", "--store-path", str(store_path), "--json"])
    disabled = json.loads(capsys.readouterr().out)
    enable_code = news_cli.main(["subscriptions", "enable", "weekly:ai", "--store-path", str(store_path), "--json"])
    enabled = json.loads(capsys.readouterr().out)
    delete_code = news_cli.main(["subscriptions", "delete", "weekly:ai", "--store-path", str(store_path), "--json"])
    deleted = json.loads(capsys.readouterr().out)

    assert disable_code == 0
    assert disabled["enabled"] is False
    assert enable_code == 0
    assert enabled["enabled"] is True
    assert delete_code == 0
    assert deleted == {"deleted": True, "subscription_id": "weekly:ai"}


def test_news_cli_subscriptions_rejects_secret_metadata(tmp_path, capsys) -> None:
    exit_code = news_cli.main(
        [
            "subscriptions",
            "create",
            "--topic",
            "AI",
            "--metadata",
            "api_key=hidden",
            "--store-path",
            str(tmp_path / "subscriptions.json"),
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 1
    assert "secret-like key" in captured.out
