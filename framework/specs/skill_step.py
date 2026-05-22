from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class SkillStepSpec(BaseModel):
    id: str = Field(min_length=1)
    type: Literal["skill"] = "skill"
    skill: str = Field(min_length=1)
    input: dict[str, Any] = Field(default_factory=dict)
    output_key: str | None = None
    timeout_seconds: int | None = None
    retry: dict[str, Any] | None = None
    store_full_result: bool = True
    store_output: bool = True
    fail_workflow_on_error: bool = True

    model_config = ConfigDict(extra="forbid")

    @field_validator("skill")
    @classmethod
    def _skill_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("skill must not be blank")
        return value

    @field_validator("timeout_seconds")
    @classmethod
    def _timeout_positive(cls, value: int | None) -> int | None:
        if value is not None and value <= 0:
            raise ValueError("timeout_seconds must be positive")
        return value

    @field_validator("output_key")
    @classmethod
    def _output_key_not_blank(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("output_key must not be blank")
        return value

    def step_type(self) -> str:
        return "skill"

    def result_key(self) -> str:
        return f"{self.id}.result"

    def output_buffer_key(self) -> str:
        return f"{self.id}.output"

    def validate_required_fields(self) -> list[str]:
        messages: list[str] = []
        if not self.id.strip():
            messages.append("id is required")
        if self.type != "skill":
            messages.append("type must be 'skill'")
        if not self.skill.strip():
            messages.append("skill is required")
        if not isinstance(self.input, dict):
            messages.append("input must be a dict")
        if self.output_key is not None and not isinstance(self.output_key, str):
            messages.append("output_key must be a string when set")
        if self.timeout_seconds is not None and self.timeout_seconds <= 0:
            messages.append("timeout_seconds must be a positive integer when set")
        if not isinstance(self.fail_workflow_on_error, bool):
            messages.append("fail_workflow_on_error must be a bool")
        return messages

    def to_step_spec_payload(self) -> dict[str, Any]:
        payload = self.model_dump(exclude_none=True)
        payload["type"] = "skill"
        return payload


__all__ = ["SkillStepSpec"]
