from __future__ import annotations

import json

from framework.llm import FakeLLMClient

from business.boards.cross_board.workflows.daily_intelligence.profiles import (
    PROFILE_AGENTIC_OFFLINE,
)


DAILY_AGENT_FIXTURE_SCENARIO_PASS = "pass"
DAILY_AGENT_FIXTURE_SCENARIO_REWRITE_VALID = "rewrite-valid"
DAILY_AGENT_FIXTURE_SCENARIO_REWRITE_INVALID_SOURCE = "rewrite-invalid-source"
DAILY_AGENT_FIXTURE_SCENARIO_REWRITE_MISSING_EDIT = "rewrite-missing-edit"
DAILY_AGENT_FIXTURE_SCENARIOS = frozenset(
    {
        DAILY_AGENT_FIXTURE_SCENARIO_PASS,
        DAILY_AGENT_FIXTURE_SCENARIO_REWRITE_VALID,
        DAILY_AGENT_FIXTURE_SCENARIO_REWRITE_INVALID_SOURCE,
        DAILY_AGENT_FIXTURE_SCENARIO_REWRITE_MISSING_EDIT,
    }
)


def build_daily_agent_fake_llm_client(
    profile: str,
    topic: str | None = None,
    *,
    scenario: str = DAILY_AGENT_FIXTURE_SCENARIO_PASS,
) -> FakeLLMClient:
    _ = profile
    normalized_topic = (topic or "AI").strip() or "AI"
    resolved_scenario = _validate_fixture_scenario(scenario)
    return FakeLLMClient(
        [
            _agent_action(
                {
                    "research_plan": {
                        "topic": normalized_topic,
                        "sections": [
                            "Executive Summary",
                            "Top Highlights",
                            "Risk / Uncertainty / Verification Notes",
                        ],
                        "constraints": {
                            "source_boundary": "evidence_bundle",
                            "llm_mode": "offline",
                            "allow_external_sources": False,
                        },
                    },
                    "planner_notes": {
                        "mode": "offline",
                        "section_count": 3,
                    },
                }
            ),
            _agent_action(
                {
                    "analysis_result": {
                        "findings": [
                            {
                                "id": "finding-1",
                                "title": f"{normalized_topic} policy signal",
                                "summary": "AI chip policy update: Export controls and model supply chains remain central.",
                                "confidence": "medium",
                                "supporting_sources": ["https://example.com/ai-chip-policy"],
                                "inference": False,
                            }
                        ],
                        "trend_signals": [
                            {
                                "title": "Export controls remain a central policy signal",
                                "confidence": "low",
                                "inference": True,
                                "supporting_sources": ["https://example.com/ai-chip-policy"],
                            }
                        ],
                        "risk_notes": ["Evidence is limited to the deterministic offline fixture."],
                        "uncertainty_notes": ["Trend interpretation remains inferential in offline mode."],
                    },
                    "analyst_notes": {
                        "mode": "offline",
                        "evidence_boundary": "preserved",
                    },
                }
            ),
            _agent_action(
                {
                    "report_draft": _fake_report_draft(normalized_topic),
                    "writer_notes": {
                        "mode": "offline",
                        "source_boundary": "evidence_bundle",
                    },
                }
            ),
            _agent_action(
                {
                    "citation_check_result": {
                        "passed": True,
                        "cited_urls": ["https://example.com/ai-chip-policy"],
                        "unsupported_claims": [],
                        "missing_citations": [],
                    },
                    "support_matrix": {
                        "status": "supported",
                        "supported_claim_count": 1,
                        "unsupported_claim_count": 0,
                        "sections": [
                            {
                                "section_id": "executive_summary",
                                "section_title": "Executive Summary",
                                "cited_urls": ["https://example.com/ai-chip-policy"],
                                "cited_evidence_ids": [],
                                "matched_evidence_ids": [],
                                "claim_ids": ["claim_policy_update"],
                                "claim_supports": [
                                    {
                                        "claim_id": "claim_policy_update",
                                        "text": "AI chip policy update: Export controls and model supply chains remain central.",
                                        "section_id": "executive_summary",
                                        "evidence_ids": [],
                                        "cited_urls": ["https://example.com/ai-chip-policy"],
                                        "support_type": "supports",
                                        "confidence": 1.0,
                                        "severity": "low",
                                    }
                                ],
                                "matched_evidence_confidences": [1.0],
                                "coverage_score": 1.0,
                                "supported": True,
                            }
                        ],
                        "section_claim_evidence_map": {
                            "executive_summary": {
                                "claim_policy_update": [],
                            }
                        },
                        "coverage_ratio": 1.0,
                        "unsupported_sections": [],
                        "unsupported_claims": [],
                        "rejected_claim_usage": [],
                    },
                    "verification_result": {
                        "status": "pass",
                        "unsupported_claims": [],
                        "missing_citations": [],
                        "risk_level": "low",
                        "reasons": [],
                        "grounded_claims": [
                            {
                                "claim_id": "claim_policy_update",
                                "section_id": "executive_summary",
                                "status": "supported",
                                "evidence_ids": [],
                                "source_urls": ["https://example.com/ai-chip-policy"],
                                "reason": "claim is explicitly grounded in section sources",
                            }
                        ],
                    },
                    "verifier_notes": {
                        "mode": "offline",
                        "checked_sources": ["https://example.com/ai-chip-policy"],
                    },
                }
            ),
            _agent_action(_fake_editor_output(normalized_topic, resolved_scenario)),
        ]
    )


def _agent_action(output: dict) -> str:
    return json.dumps(
        {
            "action_type": "final_output",
            "output": output,
        },
        sort_keys=True,
    )


def _fake_report_draft(topic: str) -> dict:
    section_id = "executive_summary"
    claim_text = "AI chip policy update: Export controls and model supply chains remain central."
    return {
        "title": f"Daily Intelligence: {topic}",
        "sections": [
            {
                "section_id": section_id,
                "title": "Executive Summary",
                "content": claim_text,
                "sources": ["https://example.com/ai-chip-policy"],
                "evidence_ids": [],
                "claim_grounding": [
                    {
                        "claim_id": "claim_policy_update",
                        "text": claim_text,
                        "evidence_ids": [],
                        "source_urls": ["https://example.com/ai-chip-policy"],
                    }
                ],
            }
        ],
        "metadata": {
            "profile": PROFILE_AGENTIC_OFFLINE,
            "topic": topic,
            "source": "fake_llm",
        },
    }


def _fake_editor_output(topic: str, scenario: str) -> dict:
    if scenario == DAILY_AGENT_FIXTURE_SCENARIO_REWRITE_VALID:
        return {
            "editor_review": _fake_rewrite_review(),
            "edited_report_draft": _fake_edited_report_draft(topic),
            "editor_notes": {"mode": "offline", "rewrite_scenario": scenario},
        }
    if scenario == DAILY_AGENT_FIXTURE_SCENARIO_REWRITE_INVALID_SOURCE:
        return {
            "editor_review": _fake_rewrite_review(),
            "edited_report_draft": _fake_edited_report_draft(
                topic,
                sources=["https://example.com/outside-source"],
            ),
            "editor_notes": {"mode": "offline", "rewrite_scenario": scenario},
        }
    if scenario == DAILY_AGENT_FIXTURE_SCENARIO_REWRITE_MISSING_EDIT:
        return {
            "editor_review": _fake_rewrite_review(),
            "edited_report_draft": None,
            "editor_notes": {"mode": "offline", "rewrite_scenario": scenario},
        }
    return {
        "editor_review": {
            "decision": "pass",
            "quality_score": 1.0,
            "reasons": [],
            "rewrite_instructions": [],
        },
        "edited_report_draft": None,
        "editor_notes": {"mode": "offline"},
    }


def _validate_fixture_scenario(value: str) -> str:
    scenario = str(value or DAILY_AGENT_FIXTURE_SCENARIO_PASS).strip()
    if scenario not in DAILY_AGENT_FIXTURE_SCENARIOS:
        raise ValueError(f"unsupported daily agent fixture scenario: {scenario}")
    return scenario


def _fake_rewrite_review() -> dict:
    return {
        "decision": "rewrite_required",
        "quality_score": 0.82,
        "reasons": ["editor tightened unsupported wording"],
        "rewrite_instructions": ["Keep only evidence-supported policy language."],
    }


def _fake_edited_report_draft(
    topic: str,
    *,
    sources: list[str] | None = None,
) -> dict:
    claim_text = "Edited summary: AI chip policy remains focused on export controls and model supply chains."
    resolved_sources = sources or ["https://example.com/ai-chip-policy"]
    return {
        "title": f"Daily Intelligence: {topic}",
        "sections": [
            {
                "section_id": "summary",
                "title": "Summary",
                "content": claim_text,
                "sources": resolved_sources,
                "evidence_ids": [],
                "claim_grounding": [
                    {
                        "claim_id": "claim_policy_update_edited",
                        "text": claim_text,
                        "evidence_ids": [],
                        "source_urls": resolved_sources,
                    }
                ],
            }
        ],
        "metadata": {
            "profile": PROFILE_AGENTIC_OFFLINE,
            "topic": topic,
            "source": "fake_llm_editor_rewrite",
        },
    }


__all__ = [
    "DAILY_AGENT_FIXTURE_SCENARIOS",
    "DAILY_AGENT_FIXTURE_SCENARIO_PASS",
    "DAILY_AGENT_FIXTURE_SCENARIO_REWRITE_INVALID_SOURCE",
    "DAILY_AGENT_FIXTURE_SCENARIO_REWRITE_MISSING_EDIT",
    "DAILY_AGENT_FIXTURE_SCENARIO_REWRITE_VALID",
    "build_daily_agent_fake_llm_client",
]
