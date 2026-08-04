import json

import interfaces.cli.news as news_cli


def test_news_cli_tools_list_json(capsys) -> None:
    exit_code = news_cli.main(["tools", "list", "--json"])

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    tool_names = {tool["name"] for tool in payload["tools"]}

    assert exit_code == 0
    assert payload["registry_valid"] is True
    assert payload["tool_count"] > 0
    assert "report.validate" in tool_names
    assert "quality.duplicate_check" in tool_names


def test_news_cli_tools_schema_applies_policy_json(capsys) -> None:
    exit_code = news_cli.main(
        [
            "tools",
            "schema",
            "--allowed",
            "report.validate",
            "--allowed",
            "web.search",
            "--blocked",
            "web.search",
            "--json",
        ]
    )

    captured = capsys.readouterr()
    payload = json.loads(captured.out)

    assert exit_code == 0
    assert payload["agent_id"] == "cli"
    assert payload["tool_count"] == 1
    assert payload["tools"][0]["name"] == "report.validate"


def test_news_cli_dangerous_list_and_schema_have_unique_web_search(capsys) -> None:
    list_exit_code = news_cli.main(["tools", "list", "--include-dangerous", "--json"])
    list_payload = json.loads(capsys.readouterr().out)

    schema_exit_code = news_cli.main(
        [
            "tools",
            "schema",
            "--include-dangerous",
            "--allowed",
            "web.search",
            "--json",
        ]
    )
    schema_payload = json.loads(capsys.readouterr().out)

    assert list_exit_code == 0
    assert list_payload["registry_valid"] is True
    assert [tool["name"] for tool in list_payload["tools"]].count("web.search") == 1
    assert schema_exit_code == 0
    assert [tool["name"] for tool in schema_payload["tools"]] == ["web.search"]
