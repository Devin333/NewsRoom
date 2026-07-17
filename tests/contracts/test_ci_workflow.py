from __future__ import annotations

from pathlib import Path

import yaml


def test_ci_workflow_fetches_history_for_release_policy_ancestry() -> None:
    workflow = yaml.safe_load(
        Path(".github/workflows/ci.yml").read_text(encoding="utf-8")
    )
    steps = workflow["jobs"]["test"]["steps"]

    checkout = next(step for step in steps if step.get("uses") == "actions/checkout@v4")
    assert checkout["with"]["fetch-depth"] == 0


def test_ci_workflow_runs_rag_eval_promotion_gate() -> None:
    workflow = yaml.safe_load(
        Path(".github/workflows/ci.yml").read_text(encoding="utf-8")
    )
    steps = workflow["jobs"]["test"]["steps"]

    assert any(
        step.get("name") == "Run RAG eval promotion gate"
        and step.get("run") == "python -m scripts.dev test-rag-eval-gate"
        for step in steps
    )


def test_ci_workflow_runs_registered_prd_daily_sweep() -> None:
    workflow = yaml.safe_load(
        Path(".github/workflows/ci.yml").read_text(encoding="utf-8")
    )
    steps = workflow["jobs"]["test"]["steps"]

    assert any(
        step.get("name") == "Run PRD-aligned daily regression sweep"
        and step.get("run") == "python -m scripts.dev test-prd-daily"
        for step in steps
    )


def test_ci_workflow_runs_durable_event_compatibility_gate() -> None:
    workflow = yaml.safe_load(
        Path(".github/workflows/ci.yml").read_text(encoding="utf-8")
    )
    steps = workflow["jobs"]["test"]["steps"]

    assert any(
        step.get("name") == "Run durable event compatibility gate"
        and step.get("run")
        == "python -m pytest tests/infrastructure/storage/events/"
        "test_durable_event_compatibility_release.py -q"
        for step in steps
    )
