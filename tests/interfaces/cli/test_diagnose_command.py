import json

import interfaces.cli.news as news_cli


def test_news_cli_diagnose_json(monkeypatch, capsys) -> None:
    monkeypatch.setattr(news_cli, "DiagnosticApplicationService", _FakeDiagnosticService)

    exit_code = news_cli.main(["diagnose", "--json"])

    captured = capsys.readouterr()
    payload = json.loads(captured.out)

    assert exit_code == 0
    assert payload["status"] == "warning"
    assert payload["checks"][0]["check_id"] == "redis"


class _FakeDiagnosticService:
    def run(self):
        return _FakeDiagnosticResult()


class _FakeDiagnosticResult:
    status = "warning"

    def to_dict(self):
        return {
            "status": "warning",
            "summary": "1 ok, 1 warning, 0 error, 0 skipped",
            "checks": [
                {
                    "check_id": "redis",
                    "name": "Redis",
                    "status": "ok",
                    "message": "ok",
                    "details": {},
                    "remediation": None,
                },
                {
                    "check_id": "dashscope",
                    "name": "DashScope",
                    "status": "warning",
                    "message": "missing",
                    "details": {},
                    "remediation": "set key",
                },
            ],
        }
