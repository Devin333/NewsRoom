from __future__ import annotations

import pytest

from workflows.daily_intelligence.agent_outputs import (
    normalize_agent_report_draft,
    validate_editor_review,
    validate_report_draft,
    validate_verification_result,
)
from workflows.daily_intelligence.agents import (
    EDITOR_AGENT_ID,
    VERIFIER_AGENT_ID,
    WRITER_AGENT_ID,
    build_editor_agent,
    build_verifier_agent,
    build_writer_agent,
)


def test_daily_agent_ids_are_non_empty_and_unique() -> None:
    agent_ids = {WRITER_AGENT_ID, VERIFIER_AGENT_ID, EDITOR_AGENT_ID}

    assert agent_ids == {"daily.writer", "daily.verifier", "daily.editor"}
    assert all(agent_ids)


def test_daily_agent_specs_define_contract_keys() -> None:
    writer = build_writer_agent()
    verifier = build_verifier_agent()
    editor = build_editor_agent()

    assert writer.input_keys == [
        "request",
        "evidence_bundle",
        "source_errors",
        "source_pipeline_metrics",
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

    assert editor.input_keys == [
        "report_draft",
        "verification_result",
        "citation_check_result",
        "support_matrix",
        "evidence_bundle",
    ]
    assert editor.output_key == "editor_review"
    assert editor.output_schema is not None


def test_daily_agent_tool_policies_reject_undeclared_tools() -> None:
    for agent in [build_writer_agent(), build_verifier_agent(), build_editor_agent()]:
        policy = agent.resolved_tool_policy()

        assert agent.allowed_tools == []
        assert policy.require_explicit_allowlist is True
        assert policy.allows("memory.search") is False
        assert policy.allows("quality.check_citations") is False
        assert policy.allows("source.fetch_url") is False


def test_daily_agent_output_validators_accept_valid_payloads() -> None:
    assert validate_report_draft(_valid_report_draft())["title"] == "Daily Brief"
    assert validate_report_draft({"report_draft": _valid_report_draft()})[
        "sections"
    ][0]["sources"] == ["https://example.com/source"]
    assert validate_verification_result(_valid_verification_result())["status"] == "pass"
    assert validate_editor_review(_valid_editor_review())["decision"] == "pass"


def test_normalize_agent_report_draft_accepts_wrapped_or_direct_draft() -> None:
    draft = _valid_report_draft()

    assert normalize_agent_report_draft(draft) == draft
    assert normalize_agent_report_draft({"report_draft": draft}) == draft


@pytest.mark.parametrize(
    ("validator", "payload"),
    [
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
            validate_report_draft,
            {
                "title": "Daily Brief",
                "sections": [{"title": "Summary", "content": "Text", "sources": "x"}],
                "metadata": {},
            },
            "sources must be a list",
        ),
        (
            validate_verification_result,
            {
                "status": "unknown",
                "unsupported_claims": [],
                "missing_citations": [],
                "risk_level": "low",
                "reasons": [],
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


def _valid_report_draft() -> dict:
    return {
        "title": "Daily Brief",
        "sections": [
            {
                "title": "Summary",
                "content": "Source-grounded summary.",
                "sources": ["https://example.com/source"],
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
    }


def _valid_editor_review() -> dict:
    return {
        "decision": "pass",
        "quality_score": 1.0,
        "reasons": [],
        "rewrite_instructions": [],
    }
