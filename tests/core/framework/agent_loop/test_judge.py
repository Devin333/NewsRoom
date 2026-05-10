from core.framework.agent_loop import AgentAction, AgentSpec, JudgeDecision, OutputJudge


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
