"""Opt-in live proof for the production Research composition.

Run explicitly with real arXiv/LLM access:

    NEWS_RUN_LIVE_RESEARCH_E2E=1 \
    python -m pytest -m live_research_e2e \
      tests/interfaces/composition/test_research_live_e2e.py -q

The configured LLM credential must be available through
``NEWS_RESEARCH_LLM_API_KEY_ENV`` (or the production fallback settings). The
marker is deselected by default, and an explicitly selected run fails instead
of skipping when opt-in or credentials are absent. Therefore an offline smoke
run cannot make live calls and a skipped test cannot be cited as live proof.
"""

from __future__ import annotations

import os
from pathlib import Path
from uuid import uuid4

import pytest
from cryptography.fernet import Fernet

from framework.harness import HarnessEventType
from interfaces.composition.research import build_research_runtime_composition
from interfaces.composition.research_errors import ResearchCompositionError
from interfaces.composition.research_settings import ResearchRuntimeSettings
from interfaces.services.research_service import ResearchAnalyzeInput


pytestmark = pytest.mark.live_research_e2e

_DEFAULT_ARXIV_ID = "1706.03762"
_LIVE_OPT_IN = "NEWS_RUN_LIVE_RESEARCH_E2E"
_TRUTHY = frozenset({"1", "true", "yes", "on"})


def test_live_arxiv_and_llm_execute_production_research_composition(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _require_live_opt_in()
    settings = _live_settings(monkeypatch, tmp_path)
    paper_id = os.environ.get(
        "NEWS_LIVE_RESEARCH_ARXIV_ID",
        _DEFAULT_ARXIV_ID,
    ).strip()
    if not paper_id:
        pytest.fail("NEWS_LIVE_RESEARCH_ARXIV_ID must not be empty", pytrace=False)

    run_id = f"live-research-e2e-{uuid4().hex}"
    composition = build_research_runtime_composition(settings=settings)
    try:
        if not composition.available:
            error = composition.availability_error
            capabilities = () if error is None else error.capabilities
            pytest.fail(
                "production Research composition is unavailable for: "
                + ", ".join(capabilities),
                pytrace=False,
            )

        response = composition.service.analyze_paper(
            ResearchAnalyzeInput(
                paper_id=paper_id,
                source_url=f"https://arxiv.org/abs/{paper_id}",
                run_id=run_id,
                user_id="live-research-e2e",
            )
        )
        record = composition.service._run_store.get_by_run_id(run_id)

        assert record is not None
        assert response["runId"] == run_id
        assert response["paperId"] == paper_id
        assert response["status"] == "succeeded"
        assert record.result.succeeded is True
        assert record.result.quality.passed is True
        assert record.result.rag_context is not None
        assert record.result.rag_context.accepted_evidence

        phases = {entry.phase for entry in record.result.transcript.entries()}
        assert {"PLAN", "EXECUTE", "VERIFY"}.issubset(phases)
        gate_events = [
            event
            for event in record.result.trace.events
            if event.event_type is HarnessEventType.GATE_EVALUATED
        ]
        assert gate_events
        assert all(event.payload["passed"] is True for event in gate_events)

        artifact_refs = response["metadata"]["artifactRefs"]
        assert {
            "research-analysis",
            "research-reader-payload",
            "research-quality-result",
            "harness-trace",
            "harness-transcript",
        }.issubset(artifact_refs)
        assert list((settings.run_store.root / "records").glob("*.json"))
    finally:
        composition.close()


def _require_live_opt_in() -> None:
    enabled = os.environ.get(_LIVE_OPT_IN, "").strip().lower() in _TRUTHY
    if not enabled:
        pytest.fail(
            f"set {_LIVE_OPT_IN}=1 before selecting live_research_e2e",
            pytrace=False,
        )


def _live_settings(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> ResearchRuntimeSettings:
    artifact_root = tmp_path / "artifacts"
    values = dict(os.environ)
    values.update(
        {
            "NEWS_ARTIFACT_ROOT": str(artifact_root),
            "NEWS_RESEARCH_ROOT": str(tmp_path / "research"),
            "NEWS_RESEARCH_ARTIFACT_ROOT": str(artifact_root),
            "NEWS_RESEARCH_RUN_STORE_ROOT": str(tmp_path / "run-store"),
            "NEWS_RESEARCH_RAG_BACKEND": "local",
            "NEWS_RESEARCH_RAG_LOCAL_ROOT": str(tmp_path / "chunks"),
        }
    )
    monkeypatch.setenv("NEWS_ARTIFACT_ROOT", str(artifact_root))
    monkeypatch.setenv(
        "NEWS_ACTIVITY_ENCRYPTION_KEY",
        Fernet.generate_key().decode("ascii"),
    )
    monkeypatch.delenv("NEWS_DATABASE_DSN", raising=False)
    try:
        return ResearchRuntimeSettings.from_env(values, cwd=tmp_path)
    except ResearchCompositionError as exc:
        pytest.fail(
            "live Research configuration is unavailable for: "
            + ", ".join(exc.capabilities),
            pytrace=False,
        )
