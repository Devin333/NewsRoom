from __future__ import annotations

from pathlib import Path

import yaml


def test_rag_live_e2e_workflow_runs_opt_in_live_pipeline() -> None:
    workflow = yaml.safe_load(
        Path(".github/workflows/rag-live-e2e.yml").read_text(encoding="utf-8")
    )
    job = workflow["jobs"]["live-rag-e2e"]
    steps = job["steps"]

    assert workflow["on"]["workflow_dispatch"] is None
    assert workflow["on"]["schedule"][0]["cron"]
    assert job["services"]["postgres"]["image"].startswith("postgres:")
    assert job["services"]["qdrant"]["image"].startswith("qdrant/qdrant:")
    assert job["env"]["NEWS_RUN_LIVE_RESEARCH_E2E"] == "1"
    assert job["env"]["NEWS_QDRANT_URL"] == "http://localhost:6333"
    assert job["env"]["NEWS_DATABASE_DSN"].startswith("postgresql://")
    assert any(
        step.get("name") == "Run live Paper RAG Qdrant/Postgres E2E"
        and step.get("run") == "python -m scripts.dev test-rag-live-e2e"
        for step in steps
    )
