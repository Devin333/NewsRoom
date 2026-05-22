from __future__ import annotations

import json

import interfaces.cli.news as news_cli
from interfaces.cli.commands import business as business_commands
from interfaces.models.business_acceptance import AcceptanceCheck, AcceptanceResult


def test_news_cli_registers_business_command() -> None:
    assert business_commands in news_cli.COMMAND_MODULES


def test_news_business_acceptance_json(monkeypatch, tmp_path, capsys) -> None:
    calls = []
    monkeypatch.setattr(business_commands, "BusinessAcceptanceService", lambda: _FakeAcceptanceService(calls))

    exit_code = news_cli.main(
        [
            "business",
            "acceptance",
            "--artifact-root",
            str(tmp_path),
            "--run-id",
            "cli-acceptance",
            "--json",
        ]
    )
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert calls == [("full", str(tmp_path), "cli-acceptance")]
    assert payload["status"] == "passed"
    assert payload["run_id"] == "cli-acceptance"


def test_news_business_acceptance_all_boards_json(monkeypatch, tmp_path, capsys) -> None:
    calls = []
    monkeypatch.setattr(business_commands, "BusinessAcceptanceService", lambda: _FakeAcceptanceService(calls))

    exit_code = news_cli.main(["business", "acceptance", "--all-boards", "--artifact-root", str(tmp_path), "--json"])
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert calls == [("all_boards", str(tmp_path), None)]
    assert payload["summary"]["area"] == "all_boards"


def test_news_business_acceptance_cross_board_json(monkeypatch, tmp_path, capsys) -> None:
    calls = []
    monkeypatch.setattr(business_commands, "BusinessAcceptanceService", lambda: _FakeAcceptanceService(calls))

    exit_code = news_cli.main(["business", "acceptance", "--cross-board", "--artifact-root", str(tmp_path), "--json"])
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert calls == [("cross_board", str(tmp_path), None)]
    assert payload["summary"]["area"] == "cross_board"


def test_news_business_acceptance_weekly_json(monkeypatch, tmp_path, capsys) -> None:
    calls = []
    monkeypatch.setattr(business_commands, "BusinessAcceptanceService", lambda: _FakeAcceptanceService(calls))

    exit_code = news_cli.main(["business", "acceptance", "--weekly", "--artifact-root", str(tmp_path), "--json"])
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert calls == [("weekly", str(tmp_path), None)]
    assert payload["summary"]["area"] == "weekly"


def test_news_business_acceptance_eval_json(monkeypatch, tmp_path, capsys) -> None:
    calls = []
    monkeypatch.setattr(business_commands, "BusinessAcceptanceService", lambda: _FakeAcceptanceService(calls))

    exit_code = news_cli.main(["business", "acceptance", "--eval", "--artifact-root", str(tmp_path), "--json"])
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert calls == [("eval", str(tmp_path), None)]
    assert payload["summary"]["area"] == "eval"


def test_news_business_acceptance_board_json(monkeypatch, tmp_path, capsys) -> None:
    calls = []
    monkeypatch.setattr(business_commands, "BusinessAcceptanceService", lambda: _FakeAcceptanceService(calls))

    exit_code = news_cli.main(
        ["business", "acceptance", "--board", "ai_news", "--artifact-root", str(tmp_path), "--json"]
    )
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert calls == [("board", str(tmp_path), "ai_news", None)]
    assert payload["summary"]["board_type"] == "ai_news"


class _FakeAcceptanceService:
    def __init__(self, calls: list) -> None:
        self.calls = calls

    def run_board_acceptance(self, board_type, *, artifact_root, run_id=None):
        self.calls.append(("board", str(artifact_root), board_type, run_id))
        return _result(run_id or f"fake-{board_type}", str(artifact_root), {"board_type": board_type})

    def run_all_board_acceptance(self, *, artifact_root, run_id_prefix=None):
        self.calls.append(("all_boards", str(artifact_root), run_id_prefix))
        return _result(run_id_prefix or "fake-all", str(artifact_root), {"area": "all_boards"})

    def run_cross_board_acceptance(self, *, artifact_root, run_id=None):
        self.calls.append(("cross_board", str(artifact_root), run_id))
        return _result(run_id or "fake-cross", str(artifact_root), {"area": "cross_board"})

    def run_weekly_acceptance(self, *, artifact_root, run_id=None):
        self.calls.append(("weekly", str(artifact_root), run_id))
        return _result(run_id or "fake-weekly", str(artifact_root), {"area": "weekly"})

    def run_eval_acceptance(self, *, artifact_root, run_id=None):
        self.calls.append(("eval", str(artifact_root), run_id))
        return _result(run_id or "fake-eval", str(artifact_root), {"area": "eval"})

    def run_full_acceptance(self, *, artifact_root, run_id=None):
        self.calls.append(("full", str(artifact_root), run_id))
        return _result(run_id or "fake-full", str(artifact_root), {"area": "full"})


def _result(run_id: str, artifact_root: str, summary: dict) -> AcceptanceResult:
    return AcceptanceResult.from_checks(
        run_id=run_id,
        artifact_root=artifact_root,
        checks=[AcceptanceCheck("fake", "cli", True, "ok", {})],
        summary=summary,
    )
