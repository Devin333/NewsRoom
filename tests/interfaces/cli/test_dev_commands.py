from __future__ import annotations

import json

from interfaces.cli.commands import dev
from interfaces.cli.news import build_parser


class _Result:
    def to_dict(self) -> dict[str, object]:
        return {
            "status": "succeeded",
            "run_id": "run-1",
            "graph_ref": "test-agent-loop.graph@1#sha256:" + "a" * 64,
            "artifact_path": "artifacts/run-1/manifest.json",
            "llm_calls": 3,
            "tool_calls": 1,
        }


class _Service:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def run(self, **kwargs):
        self.calls.append(kwargs)
        return _Result()


def test_dev_agent_loop_command_invokes_application_service(
    monkeypatch,
    capsys,
) -> None:
    service = _Service()
    roots: list[str] = []
    monkeypatch.setattr(
        dev,
        "build_agent_loop_graph_smoke_service",
        lambda *, artifact_root: roots.append(artifact_root) or service,
    )
    args = build_parser().parse_args(
        [
            "dev",
            "run-test-agent-loop",
            "--topic",
            "graph-only",
            "--artifact-root",
            "smoke-root",
            "--run-id",
            "run-1",
            "--json",
        ]
    )

    exit_code = args.handler(args)

    assert exit_code == 0
    assert roots == ["smoke-root"]
    assert service.calls == [{"topic": "graph-only", "run_id": "run-1"}]
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "succeeded"
    assert payload["llm_calls"] == 3
    assert payload["tool_calls"] == 1


def test_dev_agent_loop_human_output_contains_operator_fields(
    monkeypatch,
    capsys,
) -> None:
    monkeypatch.setattr(
        dev,
        "build_agent_loop_graph_smoke_service",
        lambda **_kwargs: _Service(),
    )
    args = build_parser().parse_args(["dev", "run-test-agent-loop"])

    assert args.handler(args) == 0

    output = capsys.readouterr().out
    for field in (
        "status=succeeded",
        "run_id=run-1",
        "graph_ref=test-agent-loop.graph@1#sha256:",
        "artifact_path=artifacts/run-1/manifest.json",
        "llm_calls=3",
        "tool_calls=1",
    ):
        assert field in output
