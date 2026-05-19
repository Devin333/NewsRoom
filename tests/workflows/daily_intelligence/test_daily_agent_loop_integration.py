from __future__ import annotations

from core.framework.agent_loop import AgentAction, AgentLoopStatus, AgentSpec, JudgeDecision
from core.framework.llm import FakeLLMClient
from domain.sources import Lineage
from evidence.models import EvidenceBundle, EvidenceItem, VerifiedClaim, VerifiedFindings
from workflows.daily_intelligence.agent_loop_integration import build_daily_output_judge
from workflows.daily_intelligence.agent_registry import build_daily_agent_runner


def _writer(**kwargs) -> AgentSpec:
    defaults = {
        "agent_id": "daily.writer",
        "name": "WriterAgent",
        "role": "Write",
        "goal": "Draft from evidence",
        "instructions": "Return JSON",
        "input_keys": ["request"],
        "output_key": "report_draft",
        "allowed_tools": ["artifact.load"],
        "output_schema": {
            "type": "object",
            "required": ["report_draft"],
            "properties": {
                "report_draft": {
                    "type": "object",
                    "required": ["title", "sections"],
                    "properties": {
                        "title": {"type": "string"},
                        "sections": {"type": "array"},
                    },
                }
            },
        },
    }
    defaults.update(kwargs)
    return AgentSpec(**defaults)


def _verifier(**kwargs) -> AgentSpec:
    defaults = {
        "agent_id": "daily.verifier",
        "name": "VerifierAgent",
        "role": "Verify",
        "goal": "Verify grounded claims",
        "instructions": "Return JSON",
        "input_keys": ["report_draft", "evidence_bundle"],
        "output_key": "verification_result",
        "allowed_tools": [],
        "output_schema": {
            "type": "object",
            "required": ["verification_result"],
            "properties": {
                "verification_result": {
                    "type": "object",
                    "required": ["grounded_claims"],
                    "properties": {
                        "grounded_claims": {"type": "array"},
                    },
                }
            },
        },
    }
    defaults.update(kwargs)
    return AgentSpec(**defaults)


def _bundle() -> EvidenceBundle:
    return EvidenceBundle(
        bundle_id="bundle-1",
        items=[
            EvidenceItem(
                evidence_id="ev-1",
                source_url="https://example.com/model",
                title="Vendor released a model update",
                summary="The model update improves inference latency.",
                confidence=0.9,
                source_id="source-1",
                source_item_id="source-item-1",
                lineage=Lineage(source_id="source-1", source_item_id="source-item-1"),
            )
        ],
    )


def test_daily_judge_retries_report_claim_outside_evidence_boundary() -> None:
    verdict = build_daily_output_judge().judge(
        agent=_writer(output_key="final_report"),
        action=AgentAction(
            action_type="final_output",
            output={
                "final_report": {
                    "title": "Daily Brief",
                    "sections": [
                        {
                            "title": "Unsupported",
                            "content": "The vendor acquired a rival.",
                            "sources": ["https://example.com/model"],
                        }
                    ],
                }
            },
        ),
        called_tools=[],
        inputs={"evidence_bundle": _bundle()},
    )

    assert verdict.decision == JudgeDecision.RETRY
    assert verdict.quality_errors == [
        "unsupported claim outside evidence: Unsupported: The vendor acquired a rival."
    ]


def test_daily_judge_retries_editor_claim_outside_evidence_boundary() -> None:
    verdict = build_daily_output_judge().judge(
        agent=_writer(agent_id="daily.editor", name="EditorAgent", output_key="edited_report"),
        action=AgentAction(
            action_type="final_output",
            output={
                "edited_report": {
                    "title": "Edited Brief",
                    "sections": [
                        {
                            "title": "Edit",
                            "content": (
                                "The vendor released a model update and expanded into robotics."
                            ),
                            "sources": ["https://example.com/model"],
                        }
                    ],
                }
            },
        ),
        called_tools=[],
        inputs={"evidence_bundle": _bundle()},
    )

    assert verdict.decision == JudgeDecision.RETRY
    assert verdict.quality_errors == [
        (
            "unsupported claim outside evidence: "
            "Edit: The vendor released a model update and expanded into robotics."
        )
    ]


def test_daily_judge_schema_pass_does_not_replace_quality_gate_for_citation_coverage() -> None:
    verdict = build_daily_output_judge().judge(
        agent=_writer(),
        action=AgentAction(
            action_type="final_output",
            output={
                "report_draft": {
                    "title": "Daily Brief",
                    "sections": [
                        {
                            "title": "Latency",
                            "content": "The model update improves inference latency.",
                            "sources": [],
                        }
                    ],
                }
            },
        ),
        called_tools=[],
        inputs={"evidence_bundle": _bundle()},
    )

    assert verdict.decision == JudgeDecision.RETRY
    assert verdict.schema_errors == []
    assert "missing section sources: Latency" in verdict.quality_errors
    assert any(
        error.startswith("unsupported claim outside evidence:")
        for error in verdict.quality_errors
    )


def test_daily_judge_blocks_unsupported_evidence_id() -> None:
    verdict = build_daily_output_judge().judge(
        agent=_writer(),
        action=AgentAction(
            action_type="final_output",
            output={
                "report_draft": {
                    "title": "Daily Brief",
                    "sections": [],
                    "supporting_evidence_ids": ["ev-999"],
                }
            },
        ),
        called_tools=[],
        inputs={"evidence_bundle": _bundle()},
    )

    assert verdict.decision == JudgeDecision.BLOCK
    assert verdict.feedback == "unsupported evidence id referenced"
    assert verdict.policy_violations == ["evidence id outside boundary: ev-999"]


def test_daily_judge_blocks_verifier_grounding_with_mutated_evidence_id() -> None:
    verdict = build_daily_output_judge().judge(
        agent=_verifier(),
        action=AgentAction(
            action_type="final_output",
            output={
                "verification_result": {
                    "grounded_claims": [
                        {
                            "claim_id": "claim-1",
                            "section_id": "summary",
                            "status": "supported",
                            "evidence_ids": ["ev-1x"],
                            "source_urls": ["https://example.com/model"],
                            "reason": "copied from report grounding",
                        }
                    ]
                }
            },
        ),
        called_tools=[],
        inputs={"evidence_bundle": _bundle()},
    )

    assert verdict.decision == JudgeDecision.BLOCK
    assert verdict.feedback == "unsupported evidence id referenced"
    assert verdict.policy_violations == ["evidence id outside boundary: ev-1x"]


def test_daily_agent_runner_normalizes_agentic_live_writer_output_to_grounded_cards() -> None:
    llm = FakeLLMClient(
        [
            '{"action_type":"final_output","output":{"report_draft":{"title":"Daily Intelligence: AI agents","sections":[{"section_id":"executive_summary","title":"Executive Summary of Key Developments","content":"Placeholder summary","sources":[],"claim_grounding":[{"claim_id":"claim_bad","text":"Placeholder summary","evidence_ids":[],"source_urls":["https://example.com/outside"]}]},{"section_id":"empty_section","title":"Regulatory and Ethical Considerations","content":"No evidence available for this section.","sources":[],"claim_grounding":[]}],"metadata":{}}}}'
        ]
    )
    agent = _writer(
        input_keys=["request", "evidence_bundle", "verified_findings"],
        output_schema={
            "type": "object",
            "required": ["report_draft"],
            "properties": {"report_draft": {"type": "object"}},
        },
    )
    evidence_bundle = EvidenceBundle(
        bundle_id="bundle-1",
        items=[
            EvidenceItem(
                evidence_id="ev-1",
                source_url="https://example.com/model",
                title="Vendor released a model update",
                summary="The model update improves inference latency.",
                confidence=0.9,
                source_id="source-1",
                source_item_id="source-item-1",
                lineage=Lineage(source_id="source-1", source_item_id="source-item-1"),
            )
        ],
    )
    verified_findings = VerifiedFindings(
        accepted_claims=[
            VerifiedClaim(
                claim_id="claim-1",
                claim="Vendor released a model update: The model update improves inference latency.",
                status="accepted",
                confidence=0.9,
                supporting_evidence_ids=["ev-1"],
                supporting_sources=["https://example.com/model"],
                section_id="evidence",
            )
        ]
    )

    result = build_daily_agent_runner(
        profile="agentic-live",
        llm_client=llm,
    ).run(
        agent,
        {
            "request": {"topic": "AI agents", "profile": "agentic-live"},
            "evidence_bundle": evidence_bundle,
            "verified_findings": verified_findings,
        },
    )

    assert result.success is True
    assert result.status == AgentLoopStatus.ACCEPTED
    assert result.output["report_draft"]["sections"] == [
        {
            "section_id": "vendor_released_a_model_update",
            "title": "Vendor released a model update",
            "content": "Vendor released a model update: The model update improves inference latency.",
            "sources": ["https://example.com/model"],
            "evidence_ids": ["ev-1"],
            "claim_grounding": [
                {
                    "claim_id": "claim-1",
                    "text": "Vendor released a model update: The model update improves inference latency.",
                    "evidence_ids": ["ev-1"],
                    "source_urls": ["https://example.com/model"],
                }
            ],
        }
    ]
    assert result.output["report_draft"]["metadata"]["writer_normalized_from_verified_findings"] is True
