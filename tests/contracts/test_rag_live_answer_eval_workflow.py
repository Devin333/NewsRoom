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


def test_run_live_answer_eval_dev_command_passes_real_corpus_options() -> None:
    args = dev.build_parser().parse_args([
        "run-live-answer-eval",
        "--golden-set",
        "data/eval/golden_set.json",
        "--papers-dir",
        ".newsroom/papers",
        "--output-dir",
        ".newsroom/eval/live-answer-real",
        "--threshold",
        "answer.success_rate=0.6",
    ])

    assert dev._rag_live_answer_eval_command(args) == [
        dev.sys.executable,
        "-m",
        "business.research.rag.cli.run_live_answer_eval",
        "--output-dir",
        ".newsroom/eval/live-answer-real",
        "--golden-set",
        "data/eval/golden_set.json",
        "--papers-dir",
        ".newsroom/papers",
        "--threshold",
        "answer.success_rate=0.6",
    ]


def test_check_live_answer_readiness_dev_command_is_registered() -> None:
    args = dev.build_parser().parse_args([
        "check-live-answer-readiness",
        "--golden-set",
        "data/eval/golden_set.json",
        "--papers-dir",
        ".newsroom/papers",
        "--output-dir",
        ".newsroom/eval/live-answer-readiness",
    ])

    assert args.command == "check-live-answer-readiness"
    assert dev._rag_live_answer_readiness_command(args) == [
        dev.sys.executable,
        "-m",
        "business.research.rag.cli.check_live_answer_readiness",
        "--output-dir",
        ".newsroom/eval/live-answer-readiness",
        "--golden-set",
        "data/eval/golden_set.json",
        "--papers-dir",
        ".newsroom/papers",
    ]


def test_rag_live_answer_eval_workflow_runs_secret_guarded_command() -> None:
    workflow = yaml.safe_load(
        Path(".github/workflows/rag-live-answer-eval.yml").read_text(encoding="utf-8")
    )
    job = workflow["jobs"]["live-answer-eval"]
    steps = job["steps"]
    step_names = [step.get("name") for step in steps]

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
    readiness_step = next(
        step
        for step in steps
        if step.get("name") == "Check live Paper RAG answer readiness"
    )
    skip_index = step_names.index("Skip live Paper RAG answer eval when LLM secrets are missing")
    readiness_index = step_names.index("Check live Paper RAG answer readiness")
    assert readiness_index < skip_index
    assert readiness_step.get("run") == "python -m scripts.dev check-live-answer-readiness"
    assert any(
        step.get("name") == "Run live Paper RAG answer eval"
        and step.get("run") == "python -m scripts.dev run-live-answer-eval"
        and "OPENAI_BASE_URL" in step.get("if", "")
        and "OPENAI_API_KEY" in step.get("if", "")
        for step in steps
    )
    real_step = next(
        step
        for step in steps
        if step.get("name") == "Run real-corpus Paper RAG answer eval when artifacts exist"
    )
    assert "OPENAI_BASE_URL" in real_step.get("if", "")
    assert "OPENAI_API_KEY" in real_step.get("if", "")
    assert "data/eval/golden_set.json" in real_step["run"]
    assert "--papers-dir .newsroom/papers" in real_step["run"]
    assert "Skipping real-corpus live answer eval" in real_step["run"]
    readiness_upload = next(
        step
        for step in steps
        if step.get("name") == "Upload live answer readiness artifacts"
    )
    assert readiness_upload.get("if") == "${{ always() }}"
    assert readiness_upload.get("uses") == "actions/upload-artifact@v4"
    assert readiness_upload.get("with", {}).get("path") == ".newsroom/eval/live-answer-readiness"
    assert any(
        step.get("name") == "Upload live answer eval artifacts"
        and step.get("uses") == "actions/upload-artifact@v4"
        and ".newsroom/eval/live-answer" in step.get("with", {}).get("path")
        and ".newsroom/eval/live-answer-real" in step.get("with", {}).get("path")
        for step in steps
    )
