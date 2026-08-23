from __future__ import annotations

import json
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field

from framework.agent.loop import AgentLoop
from framework.agent.models import AgentLoopPolicy, AgentSpec
from framework.agent.skill_selection import SkillExposurePolicy, SkillSelectionPolicy
from framework.llm import FakeLLMClient
from framework.tool import ToolExecutor, ToolRegistry


class FakeSkillMetadata(BaseModel):
    name: str
    description: str = "Extract normalized entities without loading full SKILL.md"
    category: str = "extraction"
    tags: list[str] = ["entity"]
    risk_level: str = "medium"
    status: str = "active"
    input_schema: str | None = "schemas/input.schema.json"
    raw_skill_md: str = "SHOULD_NOT_APPEAR"

    def canonical_name(self) -> str:
        return self.name.lower()

    def is_active(self) -> bool:
        return self.status == "active"


class FakeSkillRegistry:
    def __init__(self, skills: list[FakeSkillMetadata]) -> None:
        self._skills = {skill.name: skill for skill in skills}

    def list_all(self, include_disabled: bool = False) -> list[FakeSkillMetadata]:
        if include_disabled:
            return list(self._skills.values())
        return [skill for skill in self._skills.values() if skill.is_active()]

    def get(self, name: str) -> FakeSkillMetadata | None:
        return self._skills.get(name)


class FakeSkillRunStatus(str, Enum):
    SUCCESS = "success"
    FAILED = "failed"


class FakeSkillErrorDetail(BaseModel):
    code: str
    message: str


class FakeSkillResult(BaseModel):
    skill_name: str
    version: str = "1.0.0"
    status: FakeSkillRunStatus
    output: dict[str, Any] = Field(default_factory=dict)
    errors: list[FakeSkillErrorDetail] = Field(default_factory=list)
    warnings: list[FakeSkillErrorDetail] = Field(default_factory=list)
    quality_gate_results: list[dict[str, Any]] = Field(default_factory=list)
    cost: dict[str, Any] = Field(default_factory=dict)


class FakeSkillRunner:
    def __init__(self, result: FakeSkillResult):
        self.result = result
        self.calls = []

    def run(self, skill_name, input_data, context=None):
        self.calls.append(
            {"skill_name": skill_name, "input_data": input_data, "context": context}
        )
        return self.result


def test_agent_loop_calls_skill_runner_for_skill_call() -> None:
    runner = FakeSkillRunner(
        FakeSkillResult(
            skill_name="entity-extraction",
            status=FakeSkillRunStatus.SUCCESS,
            output={"summary": "entities extracted", "entities": ["OpenAI"]},
        )
    )
    llm = FakeLLMClient(
        [
            json.dumps(
                {
                    "type": "skill_call",
                    "skill_name": "entity-extraction",
                    "arguments": {"item": {"title": "Example"}},
                }
            ),
            json.dumps(
                {
                    "action_type": "final_output",
                    "output": {"output": {"summary": "done"}},
                }
            ),
        ]
    )

    result = _run_loop(llm=llm, runner=runner)

    assert result.success is True
    assert runner.calls[0]["skill_name"] == "entity-extraction"
    assert runner.calls[0]["input_data"] == {"item": {"title": "Example"}}


def test_skill_observation_enters_next_round_context() -> None:
    runner = FakeSkillRunner(
        FakeSkillResult(
            skill_name="entity-extraction",
            status=FakeSkillRunStatus.SUCCESS,
            output={"summary": "entities extracted"},
        )
    )
    llm = FakeLLMClient(
        [
            json.dumps({"type": "skill_call", "skill_name": "entity-extraction"}),
            json.dumps(
                {
                    "action_type": "final_output",
                    "output": {"output": {"summary": "done"}},
                }
            ),
        ]
    )

    _run_loop(llm=llm, runner=runner)

    second_request_text = llm.requests[1].estimated_prompt_text()
    assert "skill_observation" in second_request_text
    assert "entity-extraction" in second_request_text
    assert "entities extracted" in second_request_text


def test_failed_skill_runner_result_does_not_crash_loop() -> None:
    runner = FakeSkillRunner(
        FakeSkillResult(
            skill_name="entity-extraction",
            status=FakeSkillRunStatus.FAILED,
            errors=[FakeSkillErrorDetail(code="failed", message="skill failed")],
        )
    )
    llm = FakeLLMClient(
        [
            json.dumps({"type": "skill_call", "skill_name": "entity-extraction"}),
            json.dumps(
                {
                    "action_type": "final_output",
                    "output": {"output": {"summary": "done after failure"}},
                }
            ),
        ]
    )

    result = _run_loop(llm=llm, runner=runner)

    assert result.success is True
    assert "skill failed" in llm.requests[1].estimated_prompt_text()


def test_high_risk_skill_call_is_rejected() -> None:
    runner = FakeSkillRunner(
        FakeSkillResult(
            skill_name="entity-extraction",
            status=FakeSkillRunStatus.SUCCESS,
            output={"summary": "should not run"},
        )
    )
    llm = FakeLLMClient(
        [
            json.dumps({"type": "skill_call", "skill_name": "entity-extraction"}),
            json.dumps(
                {
                    "action_type": "final_output",
                    "output": {"output": {"summary": "done"}},
                }
            ),
        ]
    )

    result = _run_loop(
        llm=llm,
        runner=runner,
        skills=[FakeSkillMetadata(name="entity-extraction", risk_level="high")],
    )

    assert result.success is True
    assert runner.calls == []
    assert "Skill is not allowed by exposure policy" in llm.requests[1].estimated_prompt_text()


def test_available_skills_prompt_contains_metadata_only() -> None:
    runner = FakeSkillRunner(
        FakeSkillResult(
            skill_name="entity-extraction",
            status=FakeSkillRunStatus.SUCCESS,
            output={"summary": "done"},
        )
    )
    llm = FakeLLMClient(
        [
            json.dumps(
                {
                    "action_type": "final_output",
                    "output": {"output": {"summary": "done"}},
                }
            )
        ]
    )

    _run_loop(llm=llm, runner=runner)

    prompt = llm.requests[0].estimated_prompt_text()
    assert "Available Skills:" in prompt
    assert "entity-extraction" in prompt
    assert "schemas/input.schema.json" in prompt
    assert "SHOULD_NOT_APPEAR" not in prompt


def _run_loop(
    *,
    llm: FakeLLMClient,
    runner: FakeSkillRunner,
    skills: list[FakeSkillMetadata] | None = None,
):
    registry = ToolRegistry()
    skill_registry = FakeSkillRegistry(
        skills or [FakeSkillMetadata(name="entity-extraction")]
    )
    agent = AgentSpec(
        agent_id="agent-skill",
        name="Skill Agent",
        instructions="Use available skills when helpful.",
        loop_policy=AgentLoopPolicy(max_iterations=3),
    )
    return AgentLoop(
        llm_client=llm,
        tool_executor=ToolExecutor(registry),
        skill_registry=skill_registry,
        skill_runner=runner,
        skill_selection_policy=SkillSelectionPolicy(
            exposure_policy=SkillExposurePolicy()
        ),
    ).run(
        agent,
        {"topic": "extract entities"},
        [],
        run_id="agent-run-1",
        standalone=True,
    )
