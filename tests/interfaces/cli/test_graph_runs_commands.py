from __future__ import annotations

import json

import interfaces.cli.news as news_cli
from business.research.graphs.contracts import RESEARCH_PAPER_ANALYSIS_GRAPH_ID
from tests.fixtures.graph_runs import write_graph_terminal_run


def test_graph_runs_cli_lists_graph_identity(tmp_path, capsys) -> None:
    write_graph_terminal_run(tmp_path, "run-1")

    exit_code = news_cli.main(
        ["runs", "list", "--artifact-root", str(tmp_path), "--json"]
    )

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert payload["run_count"] == 1
    assert payload["runs"][0]["graph_id"] == RESEARCH_PAPER_ANALYSIS_GRAPH_ID
    assert payload["runs"][0]["graph_version"] == "1"


def test_graph_runs_cli_replay_verifies_artifact_integrity(tmp_path, capsys) -> None:
    fixture = write_graph_terminal_run(tmp_path, "run-1")
    fixture.artifact_path("output").write_text('{"result":"tampered"}', encoding="utf-8")

    exit_code = news_cli.main(
        ["runs", "replay", "run-1", "--artifact-root", str(tmp_path), "--json"]
    )

    captured = capsys.readouterr()
    assert exit_code == 1
    assert captured.out == ""
    assert "Graph artifact content" in captured.err
    assert "tampered" not in captured.err


def test_graph_runs_cli_events_uses_graph_route_and_sse_shape(monkeypatch, capsys) -> None:
    class _Inspection:
        def get_run_events(self, run_id, **kwargs):
            class _Result:
                def to_dict(self):
                    return {
                        "run_id": run_id,
                        "event_count": 1,
                        "events": [{"event_type": "graph.run.started", "sequence": 1}],
                        "events_path": None,
                        "availability": "available",
                    }

            return _Result()

    monkeypatch.setattr(
        "interfaces.cli.commands.runs.graph_run_inspection_service_from_env",
        lambda *args, **kwargs: _Inspection(),
    )

    exit_code = news_cli.main(["runs", "events", "run-1", "--sse"])

    assert exit_code == 0
    assert "event: graph.run.started\n" in capsys.readouterr().out
