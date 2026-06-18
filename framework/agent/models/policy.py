from __future__ import annotations

from dataclasses import dataclass
from typing import Any


__all__ = ["AgentLoopPolicy"]


@dataclass(frozen=True)
class AgentLoopPolicy:
    max_iterations: int = 8
    max_tool_calls: int = 20
    allow_parallel_tool_calls: bool = False
    require_final_answer: bool = True
    stop_on_tool_error: bool = False
    memory_recall_enabled: bool = True
    memory_write_enabled: bool = True
    max_judge_retries: int = 2
    max_parser_errors: int = 2
    max_repeated_tool_calls: int = 2
    max_consecutive_tool_failures: int = 3
    stop_on_first_valid_output: bool = True
    stall_detection_enabled: bool = True
    trace_enabled: bool = True
    max_trace_preview_chars: int = 500
    llm_streaming_enabled: bool = False
    conversation_compaction_enabled: bool = True
    conversation_compaction_max_messages: int = 50
    conversation_compaction_keep_last: int = 10
    allow_subagents: bool = False

    def __post_init__(self) -> None:
        _validate_non_negative("max_iterations", self.max_iterations, minimum=1)
        _validate_non_negative("max_tool_calls", self.max_tool_calls)
        _validate_non_negative("max_judge_retries", self.max_judge_retries)
        _validate_non_negative("max_parser_errors", self.max_parser_errors)
        _validate_non_negative("max_repeated_tool_calls", self.max_repeated_tool_calls)
        _validate_non_negative(
            "max_consecutive_tool_failures",
            self.max_consecutive_tool_failures,
        )
        _validate_non_negative("max_trace_preview_chars", self.max_trace_preview_chars)
        _validate_non_negative(
            "conversation_compaction_max_messages",
            self.conversation_compaction_max_messages,
            minimum=1,
        )
        _validate_non_negative(
            "conversation_compaction_keep_last",
            self.conversation_compaction_keep_last,
        )

    def validate(self) -> list[str]:
        issues: list[str] = []
        _append_validation_issue(issues, "max_iterations", self.max_iterations, minimum=1)
        _append_validation_issue(issues, "max_tool_calls", self.max_tool_calls)
        _append_validation_issue(issues, "max_judge_retries", self.max_judge_retries)
        _append_validation_issue(issues, "max_parser_errors", self.max_parser_errors)
        _append_validation_issue(issues, "max_repeated_tool_calls", self.max_repeated_tool_calls)
        _append_validation_issue(
            issues,
            "max_consecutive_tool_failures",
            self.max_consecutive_tool_failures,
        )
        return issues

    def to_dict(self) -> dict[str, object]:
        return {
            "max_iterations": self.max_iterations,
            "max_tool_calls": self.max_tool_calls,
            "allow_parallel_tool_calls": self.allow_parallel_tool_calls,
            "require_final_answer": self.require_final_answer,
            "stop_on_tool_error": self.stop_on_tool_error,
            "memory_recall_enabled": self.memory_recall_enabled,
            "memory_write_enabled": self.memory_write_enabled,
            "max_judge_retries": self.max_judge_retries,
            "max_parser_errors": self.max_parser_errors,
            "max_repeated_tool_calls": self.max_repeated_tool_calls,
            "max_consecutive_tool_failures": self.max_consecutive_tool_failures,
            "stop_on_first_valid_output": self.stop_on_first_valid_output,
            "stall_detection_enabled": self.stall_detection_enabled,
            "trace_enabled": self.trace_enabled,
            "max_trace_preview_chars": self.max_trace_preview_chars,
            "llm_streaming_enabled": self.llm_streaming_enabled,
            "conversation_compaction_enabled": self.conversation_compaction_enabled,
            "conversation_compaction_max_messages": self.conversation_compaction_max_messages,
            "conversation_compaction_keep_last": self.conversation_compaction_keep_last,
            "allow_subagents": self.allow_subagents,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, object]) -> "AgentLoopPolicy":
        if not isinstance(payload, dict):
            raise TypeError("AgentLoopPolicy payload must be an object")
        values: dict[str, Any] = {
            key: payload[key]
            for key in cls().to_dict()
            if key in payload
        }
        return cls(**values)


def _validate_non_negative(name: str, value: int, *, minimum: int = 0) -> None:
    if not isinstance(value, int):
        raise TypeError(f"{name} must be an integer")
    if value < minimum:
        if minimum == 0:
            raise ValueError(f"{name} must be non-negative")
        raise ValueError(f"{name} must be at least {minimum}")


def _append_validation_issue(
    issues: list[str],
    name: str,
    value: int,
    *,
    minimum: int = 0,
) -> None:
    if not isinstance(value, int):
        issues.append(f"{name} must be an integer")
    elif value < minimum:
        if minimum == 0:
            issues.append(f"{name} must be non-negative")
        else:
            issues.append(f"{name} must be at least {minimum}")
