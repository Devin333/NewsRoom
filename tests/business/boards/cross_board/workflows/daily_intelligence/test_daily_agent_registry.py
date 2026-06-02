from __future__ import annotations

import pytest

import business.boards.cross_board.workflows.daily_intelligence.agent_registry as agent_registry_module
from framework.agent import AgentLoopStatus
from business.foundation.models.source import Lineage
from business.layers.relation.evidence.models import EvidenceBundle, EvidenceItem
from business.boards.cross_board.workflows.daily_intelligence.agent_fixtures import (
    build_daily_agent_fake_llm_client,
)
from business.boards.cross_board.workflows.daily_intelligence.agent_registry import (
    PROFILE_AGENTIC_OFFLINE,
    build_daily_agent_registry,
    build_daily_agent_runner,
)
from business.boards.cross_board.workflows.daily_intelligence.agent_tools import build_daily_agent_tool_registry
from business.boards.cross_board.workflows.daily_intelligence.agents import (
    ANALYST_AGENT_ID,
    EDITOR_AGENT_ID,
    PLANNER_AGENT_ID,
    VERIFIER_AGENT_ID,
    WRITER_AGENT_ID,
)


def test_daily_agent_registry_contains_writer_verifier_and_editor() -> None:
    registry = build_daily_agent_registry()

    assert set(registry) == {
        PLANNER_AGENT_ID,
        ANALYST_AGENT_ID,
        WRITER_AGENT_ID,
        VERIFIER_AGENT_ID,
        EDITOR_AGENT_ID,
    }
    assert registry[PLANNER_AGENT_ID].agent_id == PLANNER_AGENT_ID
    assert registry[ANALYST_AGENT_ID].agent_id == ANALYST_AGENT_ID
    assert registry[WRITER_AGENT_ID].agent_id == WRITER_AGENT_ID
    assert registry[VERIFIER_AGENT_ID].agent_id == VERIFIER_AGENT_ID
    assert registry[EDITOR_AGENT_ID].agent_id == EDITOR_AGENT_ID


def test_daily_agent_registry_does_not_export_fake_llm_fixture() -> None:
    assert not hasattr(agent_registry_module, "build_daily_agent_fake_llm_client")
    assert [
        name
        for name in vars(agent_registry_module)
        if name.startswith("_fake_")
    ] == []


def test_daily_agent_tool_registry_exposes_evidence_and_quality_tools() -> None:
    tool_registry = build_daily_agent_tool_registry()
    agent_registry = build_daily_agent_registry()

    assert {tool.name for tool in tool_registry.list_tools()} == {
        "daily.evidence_search",
        "daily.source_metadata",
        "daily.citation_validate",
    }
    assert tool_registry.validate_no_conflicts().ok is True
    assert {
        tool["name"]
        for tool in tool_registry.export_schema_for_llm(
            ANALYST_AGENT_ID,
            agent_registry[ANALYST_AGENT_ID].resolved_tool_policy(),
        )
    } == {"daily.evidence_search", "daily.source_metadata"}
    assert {
        tool["name"]
        for tool in tool_registry.export_schema_for_llm(
            VERIFIER_AGENT_ID,
            agent_registry[VERIFIER_AGENT_ID].resolved_tool_policy(),
        )
    } == {"daily.citation_validate", "daily.evidence_search"}
    assert {
        tool["name"]
        for tool in tool_registry.export_schema_for_llm(
            EDITOR_AGENT_ID,
            agent_registry[EDITOR_AGENT_ID].resolved_tool_policy(),
        )
    } == {"daily.citation_validate"}


def test_daily_agent_tools_execute_against_provided_evidence_bundle() -> None:
    registry = build_daily_agent_tool_registry()
    evidence_bundle = _evidence_bundle()

    search = registry.require("daily.evidence_search").executor(
        {"evidence_bundle": evidence_bundle, "query": "chip policy"}
    )
    citation = registry.require("daily.citation_validate").executor(
        {
            "evidence_bundle": evidence_bundle,
            "report": {
                "title": "Daily Intelligence",
                "sections": [
                    {
                        "title": "Summary",
                        "content": "AI chip policy update: Export controls and model supply chains remain central.",
                        "sources": ["https://example.com/ai-chip-policy"],
                    }
                ],
            },
        }
    )

    assert search["matched_count"] == 1
    assert search["items"][0]["evidence_id"] == "ev-1"
    assert citation["passed"] is True


def test_daily_agent_runner_consumes_fake_llm_sequence() -> None:
    agent_registry = build_daily_agent_registry()
    llm = build_daily_agent_fake_llm_client(PROFILE_AGENTIC_OFFLINE, topic="AI policy")
    runner = build_daily_agent_runner(profile=PROFILE_AGENTIC_OFFLINE, llm_client=llm)

    planner_result = runner.run(
        agent_registry[PLANNER_AGENT_ID],
        {
            "request": {"topic": "AI policy"},
        },
        run_id="daily-agent-registry-test",
        step_id="planner_agent",
    )
    analyst_result = runner.run(
        agent_registry[ANALYST_AGENT_ID],
        {
            "request": {"topic": "AI policy"},
            "research_plan": planner_result.output["research_plan"],
            "evidence_bundle": _evidence_bundle(),
            "source_errors": [],
            "source_pipeline_metrics": {},
        },
        run_id="daily-agent-registry-test",
        step_id="analyst_agent",
    )
    writer_result = runner.run(
        agent_registry[WRITER_AGENT_ID],
        {
            "request": {"topic": "AI policy"},
            "research_plan": planner_result.output["research_plan"],
            "analysis_result": analyst_result.output["analysis_result"],
            "verified_findings": {},
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

    assert planner_result.success is True
    assert planner_result.status == AgentLoopStatus.ACCEPTED
    assert planner_result.output["research_plan"]["topic"] == "AI policy"

    assert analyst_result.success is True
    assert analyst_result.status == AgentLoopStatus.ACCEPTED
    assert analyst_result.output["analysis_result"]["findings"][0]["id"] == "finding-1"

    assert writer_result.output["report_draft"]["title"] == "Daily Intelligence: AI policy"
    assert writer_result.output["report_draft"]["sections"][0]["sources"] == [
        "https://example.com/ai-chip-policy"
    ]
    assert writer_result.output["report_draft"]["sections"][0]["claim_grounding"][0][
        "claim_id"
    ] == "claim_policy_update"
    assert writer_result.output["report_draft"]["sections"][0]["section_id"] == "executive_summary"

    assert verifier_result.success is True
    assert verifier_result.status == AgentLoopStatus.ACCEPTED
    assert verifier_result.output["verification_result"]["status"] == "pass"
    assert verifier_result.output["verification_result"]["grounded_claims"][0][
        "source_urls"
    ] == ["https://example.com/ai-chip-policy"]
    assert verifier_result.output["citation_check_result"]["passed"] is True
    assert verifier_result.output["support_matrix"]["section_claim_evidence_map"] == {
        "executive_summary": {"claim_policy_update": []}
    }

    assert editor_result.success is True
    assert editor_result.status == AgentLoopStatus.ACCEPTED
    assert editor_result.output["editor_review"]["decision"] == "pass"
    assert editor_result.output["edited_report_draft"] is None

    assert llm.call_count == 5


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
                lineage=Lineage(source_id="source-1", source_item_id="item-1"),
            )
        ],
    ).to_dict()
