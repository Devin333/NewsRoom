from __future__ import annotations

from pathlib import Path

import yaml

from scripts import dev


def test_run_live_answer_eval_dev_command_is_registered() -> None:
    args = dev.build_parser().parse_args(["run-live-answer-eval"])

    assert args.command == "run-live-answer-eval"
    assert dev._rag_live_answer_eval_command() == [
        dev.sys.executable,
        "-m",
        "business.research.rag.cli.run_live_answer_eval",
    ]


def test_rag_live_answer_eval_workflow_runs_secret_guarded_command() -> None:
    workflow = yaml.safe_load(
        Path(".github/workflows/rag-live-answer-eval.yml").read_text(encoding="utf-8")
    )
    job = workflow["jobs"]["live-answer-eval"]
    steps = job["steps"]

    assert workflow["on"]["workflow_dispatch"] is None
    assert workflow["on"]["schedule"][0]["cron"]
    assert job["env"]["OPENAI_BASE_URL"] == "${{ secrets.OPENAI_BASE_URL }}"
    assert job["env"]["OPENAI_API_KEY"] == "${{ secrets.OPENAI_API_KEY }}"
    assert any(
        step.get("name") == "Skip live Paper RAG answer eval when LLM secrets are missing"
        and "OPENAI_BASE_URL" in step.get("if", "")
        and "OPENAI_API_KEY" in step.get("if", "")
        for step in steps
    )
    assert any(
        step.get("name") == "Run live Paper RAG answer eval"
        and step.get("run") == "python -m scripts.dev run-live-answer-eval"
        and "OPENAI_BASE_URL" in step.get("if", "")
        and "OPENAI_API_KEY" in step.get("if", "")
        for step in steps
    )
    assert any(
        step.get("name") == "Upload live answer eval artifacts"
        and step.get("uses") == "actions/upload-artifact@v4"
        and step.get("with", {}).get("path") == ".newsroom/eval/live-answer"
        for step in steps
    )
