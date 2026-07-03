from __future__ import annotations

from pathlib import Path

import yaml


def test_ci_workflow_runs_rag_eval_promotion_gate() -> None:
    workflow = yaml.safe_load(Path(".github/workflows/ci.yml").read_text(encoding="utf-8"))
    steps = workflow["jobs"]["test"]["steps"]

    assert any(
        step.get("name") == "Run RAG eval promotion gate"
        and step.get("run") == "python -m scripts.dev test-rag-eval-gate"
        for step in steps
    )
