from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field

from framework.agent.skill_call import SkillCall
from framework.agent.skill_observation import SkillObservation


class FakeSkillRunStatus(str, Enum):
    SUCCESS = "success"
    FAILED = "failed"


class FakeSkillErrorDetail(BaseModel):
    code: str
    message: str
    traceback: str | None = None


class FakeSkillCost(BaseModel):
    input_tokens: int = 0
    output_tokens: int = 0


class FakeSkillResult(BaseModel):
    skill_name: str
    version: str = "1.0.0"
    status: FakeSkillRunStatus
    output: dict = Field(default_factory=dict)
    errors: list[FakeSkillErrorDetail] = Field(default_factory=list)
    warnings: list[FakeSkillErrorDetail] = Field(default_factory=list)
    quality_gate_results: list[dict] = Field(default_factory=list)
    cost: FakeSkillCost = Field(default_factory=FakeSkillCost)


def test_success_result_converts_to_observation() -> None:
    call = SkillCall(skill_name="entity-extraction", call_id="skill_123")
    result = FakeSkillResult(
        skill_name="entity-extraction",
        status=FakeSkillRunStatus.SUCCESS,
        output={"summary": "extracted entities", "entities": ["OpenAI"]},
    )

    observation = SkillObservation.from_skill_result(call, result)

    assert observation.status == "success"
    assert observation.output_summary == "extracted entities"
    assert observation.output["entities"] == ["OpenAI"]


def test_failed_result_keeps_error_messages_only() -> None:
    call = SkillCall(skill_name="evidence-checking", call_id="skill_123")
    result = FakeSkillResult(
        skill_name="evidence-checking",
        status=FakeSkillRunStatus.FAILED,
        errors=[
            FakeSkillErrorDetail(
                code="boom",
                message="validation failed",
                traceback="secret stack",
            )
        ],
    )

    observation = SkillObservation.from_skill_result(call, result)

    assert observation.status == "failed"
    assert observation.errors == ["validation failed"]


def test_to_agent_message_contains_skill_name_status_and_summary() -> None:
    observation = SkillObservation(
        call_id="skill_123",
        skill_name="entity-extraction",
        status="success",
        output_summary="done",
    )

    message = observation.to_agent_message()

    assert message["type"] == "skill_observation"
    assert message["name"] == "entity-extraction"
    assert "entity-extraction" in message["content"]
    assert "success" in message["content"]
    assert "done" in message["content"]


def test_long_output_is_truncated() -> None:
    call = SkillCall(skill_name="entity-extraction", call_id="skill_123")
    result = FakeSkillResult(
        skill_name="entity-extraction",
        status=FakeSkillRunStatus.SUCCESS,
        output={"text": "x" * 200},
    )

    observation = SkillObservation.from_skill_result(
        call,
        result,
        max_output_chars=80,
    )

    assert observation.output["truncated"] is True
    assert len(observation.output["preview"]) <= 80
