import json
from datetime import UTC, datetime

import interfaces.cli.news as news_cli
from infrastructure.storage.lineage import LineageRef, LocalJsonLineageStore


def test_news_cli_storage_lineage_list_json(tmp_path, capsys) -> None:
    _write_lineage(tmp_path)

    exit_code = news_cli.main(
        [
            "storage",
            "lineage",
            "list",
            "--artifact-root",
            str(tmp_path),
            "--run-id",
            "run-1",
            "--json",
        ]
    )

    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert payload["lineage_count"] == 2
    assert payload["lineage_refs"][0]["source_id"] == "raw-1"


def test_news_cli_storage_lineage_upstream_text(tmp_path, capsys) -> None:
    _write_lineage(tmp_path)

    exit_code = news_cli.main(
        [
            "storage",
            "lineage",
            "upstream",
            "--artifact-root",
            str(tmp_path),
            "--run-id",
            "run-1",
            "--target-type",
            "evidence",
            "--target-id",
            "ev-1",
        ]
    )

    captured = capsys.readouterr()

    assert exit_code == 0
    assert "query_type=upstream" in captured.out
    assert "lineage_count=2" in captured.out
    assert "source_item:raw-1 -> evidence:ev-1" in captured.out


def test_news_cli_storage_lineage_downstream_json(tmp_path, capsys) -> None:
    _write_lineage(tmp_path)

    exit_code = news_cli.main(
        [
            "storage",
            "lineage",
            "downstream",
            "--artifact-root",
            str(tmp_path),
            "--run-id",
            "run-1",
            "--source-type",
            "ranked_source_item",
            "--source-id",
            "rank-1",
            "--json",
        ]
    )

    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert payload["query_type"] == "downstream"
    assert payload["lineage_count"] == 1
    assert payload["lineage_refs"][0]["target_id"] == "ev-1"


def _write_lineage(artifact_root) -> None:
    store = LocalJsonLineageStore(artifact_root / "_records" / "lineage")
    store.record_many(
        [
            LineageRef(
                run_id="run-1",
                source_type="source_item",
                source_id="raw-1",
                target_type="evidence",
                target_id="ev-1",
                relation_type="source_to_evidence",
                created_at=datetime(2026, 5, 11, tzinfo=UTC),
            ),
            LineageRef(
                run_id="run-1",
                source_type="ranked_source_item",
                source_id="rank-1",
                target_type="evidence",
                target_id="ev-1",
                relation_type="ranked_to_evidence",
                created_at=datetime(2026, 5, 11, tzinfo=UTC),
            ),
        ]
    )
