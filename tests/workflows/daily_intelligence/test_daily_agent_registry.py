from __future__ import annotations

import pytest

from core.framework.agent_loop import AgentLoopStatus
from evidence.models import EvidenceBundle, EvidenceItem
from workflows.daily_intelligence.agent_registry import (
    PROFILE_AGENTIC_OFFLINE,
    build_daily_agent_fake_llm_client,
    build_daily_agent_registry,
    build_daily_agent_runner,
)
from workflows.daily_intelligence.agent_tools import build_daily_agent_tool_registry
from workflows.daily_intelligence.agents import (
    EDITOR_AGENT_ID,
    VERIFIER_AGENT_ID,
    WRITER_AGENT_ID,
)


def test_daily_agent_registry_contains_writer_verifier_and_editor() -> None:
    registry = build_daily_agent_registry()

    assert set(registry) == {WRITER_AGENT_ID, VERIFIER_AGENT_ID, EDITOR_AGENT_ID}
    assert registry[WRITER_AGENT_ID].agent_id == WRITER_AGENT_ID
    assert registry[VERIFIER_AGENT_ID].agent_id == VERIFIER_AGENT_ID
    assert registry[EDITOR_AGENT_ID].agent_id == EDITOR_AGENT_ID


def test_daily_agent_tool_registry_is_empty() -> None:
    registry = build_daily_agent_tool_registry()

    assert registry.list_tools() == []
    assert registry.export_schema_for_llm(WRITER_AGENT_ID) == []
    assert registry.validate_no_conflicts().tool_count == 0


def test_daily_agent_runner_consumes_fake_llm_sequence() -> None:
    agent_registry = build_daily_agent_registry()
    llm = build_daily_agent_fake_llm_client(PROFILE_AGENTIC_OFFLINE, topic="AI policy")
    runner = build_daily_agent_runner(profile=PROFILE_AGENTIC_OFFLINE, llm_client=llm)

    writer_result = runner.run(
        agent_registry[WRITER_AGENT_ID],
        {
            "request": {"topic": "AI policy"},
            "evidence_bundle": _evidence_bundle(),
            "source_errors": [],
            "source_pipeline_metrics": {},
        },
        run_id="daily-agent-registry-test",
        step_id="writer_agent",
    )
    verifier_result = runner.run(
        agent_registry[VERIFIER_AGENT_ID],
        {
            "report_draft": writer_result.output["report_draft"],
            "evidence_bundle": _evidence_bundle(),
            "candidate_claims": [],
            "verified_findings": {},
        },
        run_id="daily-agent-registry-test",
        step_id="verifier_agent",
    )
    editor_result = runner.run(
        agent_registry[EDITOR_AGENT_ID],
        {
            "report_draft": writer_result.output["report_draft"],
            "verification_result": verifier_result.output["verification_result"],
            "citation_check_result": verifier_result.output["citation_check_result"],
            "support_matrix": verifier_result.output["support_matrix"],
            "evidence_bundle": _evidence_bundle(),
        },
        run_id="daily-agent-registry-test",
        step_id="editor_agent",
    )

    assert writer_result.success is True
    assert writer_result.status == AgentLoopStatus.ACCEPTED
    assert writer_result.output["report_draft"]["title"] == "Daily Intelligence: AI policy"
    assert writer_result.metrics.llm_calls == 1

    assert verifier_result.success is True
    assert verifier_result.status == AgentLoopStatus.ACCEPTED
    assert verifier_result.output["verification_result"]["status"] == "pass"
    assert verifier_result.output["citation_check_result"]["passed"] is True

    assert editor_result.success is True
    assert editor_result.status == AgentLoopStatus.ACCEPTED
    assert editor_result.output["editor_review"]["decision"] == "pass"
    assert editor_result.output["edited_report_draft"] is None

    assert llm.call_count == 3


def test_daily_agent_registry_unknown_agent_id_is_not_returned() -> None:
    registry = build_daily_agent_registry()

    assert registry.get("daily.unknown") is None
    with pytest.raises(KeyError):
        _ = registry["daily.unknown"]


def _evidence_bundle() -> dict:
    return EvidenceBundle(
        bundle_id="bundle-1",
        items=[
            EvidenceItem(
                evidence_id="ev-1",
                source_url="https://example.com/ai-chip-policy",
                title="AI chip policy update",
                summary="Export controls and model supply chains remain central.",
                confidence=1.0,
                source_id="source-1",
                source_item_id="item-1",
            )
        ],
    ).to_dict()
