from core.framework.agent_loop import (
    AgentAction,
    AgentLoopPolicy,
    AgentSpec,
    JudgeDecision,
    OutputJudge,
)
from evidence.models import EvidenceBundle, EvidenceItem


def _agent(**kwargs) -> AgentSpec:
    defaults = {
        "agent_id": "analyst",
        "name": "Analyst",
        "role": "Analyze",
        "goal": "Return analysis",
        "instructions": "Return JSON",
        "input_keys": ["request"],
        "output_key": "analysis_result",
        "allowed_tools": ["memory.search"],
    }
    defaults.update(kwargs)
    return AgentSpec(**defaults)


def test_output_judge_accepts_valid_final_output() -> None:
    verdict = OutputJudge().judge(
        agent=_agent(),
        action=AgentAction(
            action_type="final_output",
            output={"analysis_result": {"summary": "ok"}},
        ),
        called_tools=["memory.search"],
    )

    assert verdict.decision == JudgeDecision.ACCEPT


def test_output_judge_retries_missing_output_key() -> None:
    verdict = OutputJudge().judge(
        agent=_agent(),
        action=AgentAction(action_type="final_output", output={"wrong": {}}),
        called_tools=[],
    )

    assert verdict.decision == JudgeDecision.RETRY
    assert verdict.missing_output_keys == ["analysis_result"]


def test_output_judge_blocks_subagent_delegation_by_default() -> None:
    verdict = OutputJudge().judge(
        agent=_agent(allowed_subagents=["citation_sanity_checker"]),
        action=AgentAction(
            action_type="delegate_to_subagent",
            subagent_id="citation_sanity_checker",
            subagent_task="check citations",
            handoff_reason="citation risk",
        ),
        called_tools=[],
    )

    assert verdict.decision == JudgeDecision.BLOCK
    assert verdict.feedback == (
        "subagent delegation is not allowed: citation_sanity_checker"
    )
    assert verdict.policy_violations == ["subagent delegation not allowed"]


def test_output_judge_allows_listed_subagent_as_deferred_escalation_contract() -> None:
    verdict = OutputJudge().judge(
        agent=_agent(
            agent_id="writer",
            loop_policy=AgentLoopPolicy(allow_subagents=True),
            allowed_subagents=["citation_sanity_checker"],
        ),
        action=AgentAction(
            action_type="delegate_to_subagent",
            subagent_id="citation_sanity_checker",
            subagent_task="check citations",
            handoff_reason="citation risk",
        ),
        called_tools=[],
    )

    assert verdict.decision == JudgeDecision.ESCALATE
    assert verdict.policy_violations == []
    assert verdict.quality_errors == [
        (
            "delegation handoff: parent_agent_id=writer; "
            "child_agent_id=citation_sanity_checker; handoff_reason=citation risk"
        )
    ]


def test_output_judge_blocks_secret_like_output() -> None:
    fake_secret = "sk" + "-abcdef1234567890"
    verdict = OutputJudge().judge(
        agent=_agent(),
        action=AgentAction(
            action_type="final_output",
            output={"analysis_result": {"secret": fake_secret}},
        ),
        called_tools=[],
    )

    assert verdict.decision == JudgeDecision.BLOCK


def test_output_judge_retries_source_boundary_violation() -> None:
    verdict = OutputJudge().judge(
        agent=_agent(allowed_sources=["https://example.com/a"]),
        action=AgentAction(
            action_type="final_output",
            output={"analysis_result": {"sources": ["https://example.com/b"]}},
        ),
        called_tools=[],
    )

    assert verdict.decision == JudgeDecision.RETRY
    assert "source outside boundary" in verdict.policy_violations[0]


def test_output_judge_retries_json_schema_violation() -> None:
    verdict = OutputJudge().judge(
        agent=_agent(
            output_schema={
                "type": "object",
                "required": ["analysis_result"],
                "properties": {
                    "analysis_result": {
                        "type": "object",
                        "required": ["summary"],
                        "properties": {"summary": {"type": "string"}},
                        "additionalProperties": False,
                    }
                },
                "additionalProperties": False,
            }
        ),
        action=AgentAction(
            action_type="final_output",
            output={"analysis_result": {"summary": 7}},
        ),
        called_tools=[],
    )

    assert verdict.decision == JudgeDecision.RETRY
    assert verdict.schema_errors == ["$.analysis_result.summary: expected string, got int"]


def test_output_judge_retries_json_schema_constraint_violation() -> None:
    verdict = OutputJudge().judge(
        agent=_agent(
            output_schema={
                "type": "object",
                "required": ["analysis_result"],
                "properties": {
                    "analysis_result": {
                        "type": "object",
                        "required": ["summary", "sources"],
                        "properties": {
                            "summary": {"type": "string", "minLength": 10},
                            "sources": {
                                "type": "array",
                                "minItems": 1,
                                "uniqueItems": True,
                                "items": {"type": "string", "pattern": "^https://"},
                            },
                        },
                    }
                },
            }
        ),
        action=AgentAction(
            action_type="final_output",
            output={
                "analysis_result": {
                    "summary": "short",
                    "sources": ["https://example.com/a"],
                }
            },
        ),
        called_tools=[],
    )

    assert verdict.decision == JudgeDecision.RETRY
    assert verdict.schema_errors == [
        "$.analysis_result.summary: expected string length at least 10, got 5"
    ]


def test_output_judge_retries_report_claim_outside_evidence_boundary() -> None:
    bundle = EvidenceBundle(
        bundle_id="bundle-1",
        items=[
            EvidenceItem(
                evidence_id="ev-1",
                source_url="https://example.com/a",
                title="Vendor released a model update",
                summary="The update improves inference latency.",
                confidence=0.9,
                source_id="source-1",
            )
        ],
    )

    verdict = OutputJudge().judge(
        agent=_agent(agent_id="writer", name="WriterAgent", output_key="final_report"),
        action=AgentAction(
            action_type="final_output",
            output={
                "final_report": {
                    "title": "Daily Brief",
                    "sections": [
                        {
                            "title": "Unsupported",
                            "content": "The vendor acquired a rival.",
                            "sources": ["https://example.com/a"],
                        }
                    ],
                }
            },
        ),
        called_tools=[],
        inputs={"evidence_bundle": bundle},
    )

    assert verdict.decision == JudgeDecision.RETRY
    assert verdict.quality_errors == [
        "unsupported claim outside evidence: Unsupported: The vendor acquired a rival."
    ]


def test_output_judge_retries_editor_claim_outside_evidence_boundary() -> None:
    bundle = EvidenceBundle(
        bundle_id="bundle-1",
        items=[
            EvidenceItem(
                evidence_id="ev-1",
                source_url="https://example.com/a",
                title="The model update improves inference latency",
                summary="The vendor released a model update that improves inference latency.",
                confidence=0.9,
                source_id="source-1",
            )
        ],
    )

    verdict = OutputJudge().judge(
        agent=_agent(agent_id="editor", name="EditorAgent", output_key="edited_report"),
        action=AgentAction(
            action_type="final_output",
            output={
                "edited_report": {
                    "title": "Edited Brief",
                    "sections": [
                        {
                            "title": "Edit",
                            "content": "The vendor released a model update and expanded into robotics.",
                            "sources": ["https://example.com/a"],
                        }
                    ],
                }
            },
        ),
        called_tools=[],
        inputs={"evidence_bundle": bundle},
    )

    assert verdict.decision == JudgeDecision.RETRY
    assert verdict.quality_errors == [
        (
            "unsupported claim outside evidence: "
            "Edit: The vendor released a model update and expanded into robotics."
        )
    ]
