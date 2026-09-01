from __future__ import annotations

import json

from interfaces.cli import news
from interfaces.cli.commands import paper
from interfaces.services.research_service import ResearchServiceError


class _FakeResearchService:
    def __init__(self, *, failure: Exception | None = None) -> None:
        self.failure = failure
        self.calls: list[tuple[str, object]] = []

    def parse_paper(self, command):
        self.calls.append(("parse_paper", command))
        if self.failure is not None:
            raise self.failure
        return {
            "runId": "run-cli-1",
            "paperId": "paper-cli-1",
            "status": "parsed",
            "provenance": {"sourceSnapshotRefs": ["snapshot-1"]},
        }


def test_parse_command_calls_application_service_and_emits_contract_json(monkeypatch, capsys) -> None:
    service = _FakeResearchService()
    monkeypatch.setattr(paper, "_research_service", lambda _args: service)
    args = news.build_parser().parse_args([
        "paper",
        "parse",
        "https://publisher.example/paper",
        "--tenant-id",
        "tenant-a",
        "--json",
    ])

    assert args.handler(args) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "parsed"
    assert payload["paperId"] == "paper-cli-1"
    assert payload["provenance"]["sourceSnapshotRefs"] == ["snapshot-1"]
    assert service.calls[0][0] == "parse_paper"
    assert service.calls[0][1].tenant_id == "tenant-a"


def test_parse_command_sanitizes_application_errors(monkeypatch, capsys) -> None:
    service = _FakeResearchService(
        failure=ResearchServiceError(
            "source_denied",
            "secret upstream response should not leak",
            status_code=403,
            details={"source_type": "publisher"},
            user_action_required=True,
        )
    )
    monkeypatch.setattr(paper, "_research_service", lambda _args: service)
    args = news.build_parser().parse_args([
        "paper",
        "parse",
        "https://publisher.example/restricted",
        "--json",
    ])

    assert args.handler(args) == 4
    output = capsys.readouterr().out
    payload = json.loads(output)
    assert payload["status"] == "failed"
    assert payload["error"]["code"] == "source_denied"
    assert "secret upstream" not in output
    assert payload["provenance"]["actorScope"] == {}


def test_command_exit_code_uses_highest_batch_severity() -> None:
    assert paper._command_exit_code({"status": "metadata_only"}) == 0
    assert paper._command_exit_code({"status": "degraded"}) == 0
    assert paper._command_exit_code({"status": "failed", "error": {"code": "source_timeout", "retryable": True}}) == 4
    assert paper._command_exit_code({"status": "failed", "error": {"code": "quality_failed"}}) == 5
    assert paper._command_exit_code({"status": "catalog_partial"}) == 6
    assert paper._command_exit_code({"status": "failed", "error": {"code": "run_final_persist_failed"}}) == 7
    assert paper._command_exit_code(
        {
            "status": "failed",
            "outcomes": [
                {"status": "metadata_only"},
                {"status": "failed", "error": {"code": "source_denied", "statusCode": 403}},
                {"status": "failed", "error": {"code": "run_final_persist_failed"}},
            ],
        }
    ) == 7
