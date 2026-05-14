from core.framework.agent_loop import AgentAction, AgentSpec, JudgeDecision, OutputJudge
from evidence.models import EvidenceBundle, EvidenceItem


def _writer(**kwargs) -> AgentSpec:
    defaults = {
        "agent_id": "writer",
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
            )
        ],
    )


def test_writer_schema_pass_does_not_replace_quality_gate_for_citation_coverage() -> None:
    verdict = OutputJudge().judge(
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


def test_output_judge_blocks_unsupported_evidence_id() -> None:
    verdict = OutputJudge().judge(
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


def test_output_judge_verdict_values_are_single_agent_decisions_only() -> None:
    assert {decision.value for decision in JudgeDecision} == {
        "accept",
        "retry",
        "escalate",
        "block",
    }
