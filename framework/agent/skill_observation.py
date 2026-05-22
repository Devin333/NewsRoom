from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, Field

from framework.agent.skill_call import SkillCall
from framework.shared.json import to_jsonable


class SkillObservation(BaseModel):
    type: str = "skill_observation"

    call_id: str
    skill_name: str
    status: str

    output_summary: str = ""
    output: dict[str, Any] = Field(default_factory=dict)

    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)

    quality_gate_results: list[dict[str, Any]] = Field(default_factory=list)
    cost: dict[str, Any] = Field(default_factory=dict)

    def to_agent_message(self) -> dict[str, Any]:
        """Convert observation to AgentLoop message."""
        content = {
            "skill_name": self.skill_name,
            "status": self.status,
            "summary": self.output_summary,
            "errors": list(self.errors),
        }
        return {
            "role": "tool",
            "type": self.type,
            "name": self.skill_name,
            "content": json.dumps(content, ensure_ascii=False, sort_keys=True),
        }

    @classmethod
    def from_skill_result(
        cls,
        call: SkillCall,
        result: Any,
        max_output_chars: int = 4000,
    ) -> "SkillObservation":
        """Convert SkillResult into compact observation."""
        output = _dict_or_empty(_read(result, "output", {}))
        truncated_output = _truncate_output(output, max_output_chars)
        return cls(
            call_id=call.call_id or "",
            skill_name=call.skill_name,
            status=str(_enum_value(_read(result, "status", ""))),
            output_summary=_output_summary(output, max_output_chars),
            output=truncated_output,
            errors=_error_messages(_read(result, "errors", [])),
            warnings=_warning_messages(_read(result, "warnings", [])),
            quality_gate_results=[
                dict(item)
                for item in (_read(result, "quality_gate_results", []) or [])
                if isinstance(item, dict)
            ],
            cost=_model_to_dict(_read(result, "cost", {})),
        )


def _output_summary(output: dict[str, Any], max_output_chars: int) -> str:
    summary = output.get("summary")
    if summary is not None:
        return _truncate_text(str(summary), max_output_chars)
    markdown_report = output.get("markdown_report")
    if markdown_report is not None:
        return _truncate_text(str(markdown_report), 500)
    return _truncate_text(
        json.dumps(to_jsonable(output), ensure_ascii=False, sort_keys=True),
        max_output_chars,
    )


def _truncate_output(output: dict[str, Any], max_output_chars: int) -> dict[str, Any]:
    payload = json.dumps(to_jsonable(output), ensure_ascii=False, sort_keys=True)
    if len(payload) <= max_output_chars:
        return output
    return {
        "truncated": True,
        "preview": _truncate_text(payload, max_output_chars),
    }


def _truncate_text(value: str, max_chars: int) -> str:
    if max_chars <= 0:
        return ""
    if len(value) <= max_chars:
        return value
    if max_chars <= 3:
        return value[:max_chars]
    return f"{value[: max_chars - 3]}..."


def _error_messages(errors: Any) -> list[str]:
    messages = []
    for error in errors or []:
        message = _read(error, "message", None)
        if message is None:
            message = str(error)
        messages.append(str(message))
    return messages


def _warning_messages(warnings: Any) -> list[str]:
    messages = []
    for warning in warnings or []:
        message = _read(warning, "message", None)
        if message is None:
            message = str(warning)
        messages.append(str(message))
    return messages


def _dict_or_empty(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    return {}


def _model_to_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        payload = model_dump(mode="json")
        return dict(payload) if isinstance(payload, dict) else {}
    to_dict = getattr(value, "to_dict", None)
    if callable(to_dict):
        payload = to_dict()
        return dict(payload) if isinstance(payload, dict) else {}
    return {}


def _read(value: Any, key: str, default: Any = None) -> Any:
    if isinstance(value, dict):
        return value.get(key, default)
    return getattr(value, key, default)


def _enum_value(value: Any) -> Any:
    return value.value if hasattr(value, "value") else value
