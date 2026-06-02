from __future__ import annotations

import pytest

from business.boards.cross_board.workflows.daily_intelligence.agent_outputs import (
    normalize_agent_report_draft,
    validate_analysis_result,
    validate_editor_review,
    validate_research_plan,
    validate_report_draft,
    validate_verification_result,
)
from business.boards.cross_board.workflows.daily_intelligence.agent_output_budget import (
    DAILY_AGENT_OUTPUT_BUDGET,
)
from business.boards.cross_board.workflows.daily_intelligence.agents import (
    ANALYST_AGENT_ID,
    EDITOR_AGENT_ID,
    PLANNER_AGENT_ID,
    VERIFIER_AGENT_ID,
    WRITER_AGENT_ID,
    build_analyst_agent,
    build_editor_agent,
    build_planner_agent,
    build_verifier_agent,
    build_writer_agent,
)


def test_daily_agent_ids_are_non_empty_and_unique() -> None:
    agent_ids = {PLANNER_AGENT_ID, ANALYST_AGENT_ID, WRITER_AGENT_ID, VERIFIER_AGENT_ID, EDITOR_AGENT_ID}

    assert agent_ids == {
        "daily.planner",
        "daily.analyst",
        "daily.writer",
        "daily.verifier",
        "daily.editor",
    }
    assert all(agent_ids)


def test_daily_agent_specs_define_contract_keys() -> None:
    planner = build_planner_agent()
    analyst = build_analyst_agent()
    writer = build_writer_agent()
    verifier = build_verifier_agent()
    editor = build_editor_agent()

    assert planner.input_keys == [
        "request",
        "evidence_bundle",
        "source_errors",
        "source_pipeline_metrics",
        "agent_feedback_events",
        "agent_feedback_summary",
        "agent_feedback_route",
        "agent_feedback_loop_state",
        "source_recollection_profile",
    ]
    assert planner.output_key == "research_plan"
    assert planner.output_schema is not None

    assert analyst.input_keys == [
        "request",
        "research_plan",
        "evidence_bundle",
        "source_errors",
        "source_pipeline_metrics",
    ]
    assert analyst.output_key == "analysis_result"
    assert analyst.output_schema is not None

    assert writer.input_keys == [
        "request",
        "research_plan",
        "analysis_result",
        "verified_findings",
        "evidence_bundle",
        "source_errors",
        "source_pipeline_metrics",
        "citation_check_result",
        "support_matrix",
        "verification_result",
        "agent_feedback_events",
        "agent_feedback_summary",
        "agent_feedback_route",
        "agent_feedback_loop_state",
    ]
    assert writer.output_key == "report_draft"
    assert writer.output_schema is not None

    assert verifier.input_keys == [
        "report_draft",
        "evidence_bundle",
        "candidate_claims",
        "verified_findings",
    ]
    assert verifier.output_key == "verification_result"
    assert verifier.output_schema is not None
    assert "Never invent, normalize, reformat, or partially rewrite evidence IDs" in verifier.instructions

    assert editor.input_keys == [
        "report_draft",
        "verification_result",
        "citation_check_result",
        "support_matrix",
        "evidence_bundle",
    ]
    assert editor.output_key == "editor_review"
    assert editor.output_schema is not None
    for agent in [planner, analyst, writer, verifier, editor]:
        assert agent.validation_policy["output_budget"] == DAILY_AGENT_OUTPUT_BUDGET.to_dict()


def test_daily_agent_tool_policies_reject_undeclared_tools() -> None:
    expected_allowed_tools = {
        PLANNER_AGENT_ID: ["daily.source_metadata"],
        ANALYST_AGENT_ID: ["daily.evidence_search", "daily.source_metadata"],
        WRITER_AGENT_ID: ["daily.evidence_search", "daily.section_draft"],
        VERIFIER_AGENT_ID: ["daily.citation_validate", "daily.evidence_search"],
        EDITOR_AGENT_ID: ["daily.citation_validate", "daily.section_draft"],
    }
    for agent in [
        build_planner_agent(),
        build_analyst_agent(),
        build_writer_agent(),
        build_verifier_agent(),
        build_editor_agent(),
    ]:
        policy = agent.resolved_tool_policy()

        assert agent.allowed_tools == expected_allowed_tools[agent.agent_id]
        assert policy.require_explicit_allowlist is True
        assert policy.allows("memory.search") is False
        assert policy.allows("quality.check_citations") is False
        assert policy.allows("source.fetch_url") is False
        for tool_name in expected_allowed_tools[agent.agent_id]:
            assert policy.allows(tool_name) is True
        for tool_name in {
            "daily.evidence_search",
            "daily.source_metadata",
            "daily.citation_validate",
            "daily.section_draft",
        } - set(expected_allowed_tools[agent.agent_id]):
            assert policy.allows(tool_name) is False


def test_daily_agent_output_validators_accept_valid_payloads() -> None:
    assert validate_research_plan(_valid_research_plan())["topic"] == "AI policy"
    assert validate_analysis_result(_valid_analysis_result())["findings"][0]["id"] == "finding-1"
    assert validate_report_draft(_valid_report_draft())["title"] == "Daily Brief"
    assert validate_report_draft({"report_draft": _valid_report_draft()})[
        "sections"
    ][0]["sources"] == ["https://example.com/source"]
    assert validate_report_draft(_valid_report_draft())["sections"][0]["claim_grounding"][0][
        "evidence_ids"
    ] == ["ev_1"]
    assert validate_verification_result(_valid_verification_result())["status"] == "pass"
    assert validate_verification_result(_valid_verification_result())["grounded_claims"][0][
        "status"
    ] == "supported"
    assert validate_editor_review(_valid_editor_review())["decision"] == "pass"


def test_normalize_agent_report_draft_accepts_wrapped_or_direct_draft() -> None:
    draft = _valid_report_draft()

    assert normalize_agent_report_draft(draft) == draft
    assert normalize_agent_report_draft({"report_draft": draft}) == draft


def test_validate_report_draft_backfills_sources_from_claim_grounding() -> None:
    draft = _valid_report_draft()
    draft["sections"][0]["sources"] = []

    validated = validate_report_draft(draft)

    assert validated["sections"][0]["sources"] == ["https://example.com/source"]


@pytest.mark.parametrize(
    ("validator", "payload"),
    [
        (validate_research_plan, {"topic": "AI policy"}),
        (validate_analysis_result, {"findings": []}),
        (validate_report_draft, {"title": "Daily Brief", "metadata": {}}),
        (validate_verification_result, {"status": "pass"}),
        (validate_editor_review, {"decision": "pass"}),
    ],
)
def test_daily_agent_output_validators_reject_missing_keys(validator, payload) -> None:
    with pytest.raises(ValueError, match="missing required key"):
        validator(payload)


@pytest.mark.parametrize(
    ("validator", "payload", "message"),
    [
        (
            validate_research_plan,
            {
                "topic": "",
                "sections": [],
                "constraints": {},
            },
            "topic must be a non-empty string",
        ),
        (
            validate_analysis_result,
            {
                "findings": {},
                "trend_signals": [],
                "risk_notes": [],
                "uncertainty_notes": [],
            },
            "findings must be a list",
        ),
        (
            validate_analysis_result,
            {
                "findings": [],
                "trend_signals": [],
                "risk_notes": [],
                "uncertainty_notes": [],
                "evidence_gaps": {},
            },
            "evidence_gaps must be a list",
        ),
        (
            validate_report_draft,
            {
                "title": "Daily Brief",
                "sections": [
                    {
                        "section_id": "summary",
                        "title": "Summary",
                        "content": "Text",
                        "sources": ["https://example.com/source"],
                    }
                ],
                "metadata": {},
            },
            "missing required key",
        ),
        (
            validate_report_draft,
            {
                "title": "Daily Brief",
                "sections": [
                    {
                        "section_id": "summary",
                        "title": "Summary",
                        "content": "Text",
                        "sources": ["https://example.com/source"],
                        "claim_grounding": {},
                    }
                ],
                "metadata": {},
            },
            "claim_grounding must be a list",
        ),
        (
            validate_verification_result,
            {
                "status": "pass",
                "unsupported_claims": [],
                "missing_citations": [],
                "risk_level": "low",
                "reasons": [],
                "grounded_claims": {},
            },
            "grounded_claims must be a list",
        ),
        (
            validate_report_draft,
            {
                "title": "Daily Brief",
                "sections": [
                    {
                        "section_id": "summary",
                        "title": "Summary",
                        "content": "First paragraph.\n\nSecond paragraph.",
                        "sources": ["https://example.com/source"],
                        "claim_grounding": [
                            {
                                "claim_id": "claim_1",
                                "text": "First paragraph.",
                                "evidence_ids": ["ev_1"],
                                "source_urls": ["https://example.com/source"],
                            }
                        ],
                    }
                ],
                "metadata": {},
            },
            "compact card, not multi-paragraph prose",
        ),
        (
            validate_report_draft,
            {
                "title": "Daily Brief",
                "sections": [
                    {
                        "section_id": "summary",
                        "title": "Summary",
                        "content": "Text",
                        "sources": ["https://example.com/source"],
                        "claim_grounding": [
                            {
                                "claim_id": "claim_1",
                                "text": "Text",
                                "evidence_ids": ["ev_1"],
                                "source_urls": [],
                            }
                        ],
                    }
                ],
                "metadata": {},
            },
            "source_urls must contain at least one source URL",
        ),
        (
            validate_verification_result,
            {
                "status": "unknown",
                "unsupported_claims": [],
                "missing_citations": [],
                "risk_level": "low",
                "reasons": [],
                "grounded_claims": [],
            },
            "status is not supported",
        ),
        (
            validate_verification_result,
            {
                "status": "pass",
                "unsupported_claims": [],
                "missing_citations": [],
                "risk_level": "critical",
                "reasons": [],
                "grounded_claims": [],
            },
            "risk_level is not supported",
        ),
        (
            validate_editor_review,
            {
                "decision": "publish",
                "quality_score": 1.0,
                "reasons": [],
                "rewrite_instructions": [],
            },
            "decision is not supported",
        ),
    ],
)
def test_daily_agent_output_validators_reject_invalid_values(
    validator,
    payload,
    message,
) -> None:
    with pytest.raises(ValueError, match=message):
        validator(payload)


def _valid_research_plan() -> dict:
    return {
        "topic": "AI policy",
        "sections": ["Executive Summary", "Top Highlights"],
        "constraints": {"source_boundary": "evidence_bundle"},
    }


def _valid_analysis_result() -> dict:
    return {
        "findings": [{"id": "finding-1", "summary": "Source-grounded finding."}],
        "trend_signals": [{"title": "Adoption signal", "inference": True}],
        "risk_notes": ["Single-source evidence."],
        "uncertainty_notes": ["Trend remains inferential."],
        "evidence_gaps": [{"reason": "Need a second independent policy source."}],
        "source_recollection_requests": [{"query": "AI chip policy official update"}],
        "missing_information": ["Independent confirmation of policy scope."],
    }


def _valid_report_draft() -> dict:
    return {
        "title": "Daily Brief",
        "sections": [
            {
                "section_id": "summary",
                "title": "Summary",
                "content": "Source-grounded summary.",
                "sources": ["https://example.com/source"],
                "evidence_ids": ["ev_1"],
                "claim_grounding": [
                    {
                        "claim_id": "claim_1",
                        "text": "Source-grounded summary.",
                        "evidence_ids": ["ev_1"],
                        "source_urls": ["https://example.com/source"],
                    }
                ],
            }
        ],
        "metadata": {"profile": "agentic-offline"},
    }


def _valid_verification_result() -> dict:
    return {
        "status": "pass",
        "unsupported_claims": [],
        "missing_citations": [],
        "risk_level": "low",
        "reasons": [],
        "grounded_claims": [
            {
                "claim_id": "claim_1",
                "section_id": "summary",
                "status": "supported",
                "evidence_ids": ["ev_1"],
                "source_urls": ["https://example.com/source"],
                "reason": "explicit grounding",
            }
        ],
    }


def _valid_editor_review() -> dict:
    return {
        "decision": "pass",
        "quality_score": 1.0,
        "reasons": [],
        "rewrite_instructions": [],
    }
