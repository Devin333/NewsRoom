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

    _write_research_report(
        artifact_root,
        run_id="entity-research",
        report_id="entity-research:final",
        title="Research analysis for OpenAI policy",
        content="OpenAI and ChatGPT appear in the research evidence.",
    )

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
            "--graph-id",
            "research.paper_analysis",
            "--json",
        ]
    )
    match_payload = json.loads(capsys.readouterr().out)

    assert match_code == 0
    assert match_payload["match_count"] == 1
    assert match_payload["matches"][0]["report_id"] == "entity-research:final"


def test_news_cli_entities_match_reports_accepts_graph_id(tmp_path, capsys) -> None:
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
    capsys.readouterr()
    assert create_code == 0

    _write_research_report(
        artifact_root,
        run_id="entity-family-research",
        report_id="entity-family-research:final",
        title="Research analysis for OpenAI policy",
        content="ChatGPT is mentioned in the paper summary.",
    )

    match_code = main(
        [
            "entities",
            "match-reports",
            "company:openai",
            "--store-path",
            str(store_path),
            "--artifact-root",
            str(artifact_root),
            "--graph-id",
            "research.paper_analysis",
            "--json",
        ]
    )
    match_payload = json.loads(capsys.readouterr().out)

    assert match_code == 0
    assert match_payload["graph_id"] == "research.paper_analysis"
    assert match_payload["match_count"] == 1


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


def _write_research_report(
    artifact_root,
    *,
    run_id: str,
    report_id: str,
    title: str,
    content: str,
) -> None:
    run_dir = artifact_root / run_id
    run_dir.mkdir(parents=True)
    (run_dir / "report.json").write_text(
        json.dumps({"title": title, "sections": [{"content": content}]}),
        encoding="utf-8",
    )
    (run_dir / "report.md").write_text(f"# {title}\n\n{content}", encoding="utf-8")
    (run_dir / "manifest.json").write_text(
        json.dumps(
            {
                "run_id": run_id,
                "graph_id": "research.paper_analysis",
                "graph_version": "0.1.0",
                "profile": "research",
                "status": "succeeded",
                "finished_at": "2026-05-11T00:00:00Z",
                "quality_score": 0.92,
                "artifacts": {
                    "report_json": "report.json",
                    "report_markdown": "report.md",
                },
            }
        ),
        encoding="utf-8",
    )
