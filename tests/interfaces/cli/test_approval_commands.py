from __future__ import annotations

import json

import pytest

from interfaces.cli import news as news_cli
from interfaces.cli.commands import waits


class _FakeWaits:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple, dict]] = []

    def inspect(self, run_id, node_instance_id):
        self.calls.append(("inspect", (run_id, node_instance_id), {}))
        return _wait_payload()

    def deliver_signal(self, run_id, node_instance_id, **kwargs):
        self.calls.append(("signal", (run_id, node_instance_id), kwargs))
        return {"operation": "signal", "wait": _wait_payload()}

    def decide_approval(self, run_id, node_instance_id, **kwargs):
        self.calls.append(("approval", (run_id, node_instance_id), kwargs))
        return {"operation": "approval", "wait": _wait_payload()}

    def cancel(self, run_id, node_instance_id, **kwargs):
        self.calls.append(("cancel", (run_id, node_instance_id), kwargs))
        return {"operation": "cancellation", "wait": _wait_payload()}


class _FakeClient:
    def __init__(self, *args, **kwargs):
        self.waits = _FakeWaits()


def _wait_payload() -> dict:
    return {
        "run_id": "run-1",
        "node_instance_id": "node-1",
        "wait_id": "wait-1",
        "kind": "approval",
        "status": "ready",
        "lifecycle": "running",
        "outcome": "waiting",
        "graph_id": "research.paper_analysis",
        "graph_version": "1",
        "graph_ref": "research.paper_analysis@1",
        "graph_checksum": "sha256:" + "a" * 64,
    }


def test_news_cli_approval_decision_posts_only_bounded_wait_cause(monkeypatch, capsys) -> None:
    fake = _FakeClient()
    monkeypatch.setattr(waits, "NewsClient", lambda *args, **kwargs: fake)

    exit_code = news_cli.main(
        [
            "approval-decision",
            "run-1",
            "node-1",
            "--approval-id",
            "approval-1",
            "--approve",
            "--json",
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert payload["operation"] == "approval"
    assert fake.waits.calls == [
        ("approval", ("run-1", "node-1"), {"approval_id": "approval-1", "approved": True})
    ]
    assert "buffer_updates" not in payload
    assert "resume_metadata" not in payload


def test_news_cli_wait_commands_render_graph_identity(monkeypatch, capsys) -> None:
    fake = _FakeClient()
    monkeypatch.setattr(waits, "NewsClient", lambda *args, **kwargs: fake)

    exit_code = news_cli.main(["waits", "inspect", "run-1", "node-1"])

    output = capsys.readouterr().out
    assert exit_code == 0
    assert "run_id=run-1" in output
    assert "node_instance_id=node-1" in output
    assert "graph_checksum=sha256:" in output


def test_news_cli_rejects_legacy_approval_commands_and_state_patch_flags() -> None:
    parser = news_cli.build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["approvals", "list"])
    with pytest.raises(SystemExit):
        parser.parse_args(
            [
                "approval-decision",
                "run-1",
                "node-1",
                "--approval-id",
                "approval-1",
                "--approve",
                "--node-updates",
                "{}",
            ]
        )
