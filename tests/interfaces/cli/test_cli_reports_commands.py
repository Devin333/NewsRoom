from __future__ import annotations

import json

import interfaces.cli.news as news_cli
from interfaces.cli.commands import reports as reports_commands


def test_cli_reports_list_uses_report_service_compat_path(monkeypatch, tmp_path, capsys) -> None:
    calls = []

    class FakeReportService:
        def __init__(self, *, artifact_root):
            calls.append(artifact_root)

        def list_reports(self, **kwargs):
            return _FakeResult(
                {
                    "report_count": 1,
                    "reports": [{"report_id": "r1", "run_id": "run-1", "title": "Report", "finished_at": None}],
                    **kwargs,
                }
            )

    monkeypatch.setattr(reports_commands, "ReportApplicationService", FakeReportService)

    exit_code = news_cli.main(["reports", "list", "--artifact-root", str(tmp_path), "--json"])

    assert exit_code == 0
    assert calls == [str(tmp_path)]
    assert json.loads(capsys.readouterr().out)["report_count"] == 1


class _FakeResult:
    def __init__(self, payload):
        self.payload = payload

    def to_dict(self):
        return self.payload
