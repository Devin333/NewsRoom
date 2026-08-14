from __future__ import annotations

from dataclasses import dataclass, field
import math
from typing import Any

from framework.tool.models.status import ToolSideEffect
from framework.tool.models.result_persistence import ToolResultPersistenceContract
from framework.tool.runtime.errors import ToolDefinitionError


@dataclass(frozen=True)
class ToolDefinition:
    name: str
    description: str = ""
    input_schema: dict[str, Any] = field(default_factory=dict)
    output_schema: dict[str, Any] | None = None
    side_effect: ToolSideEffect | str = "none"
    concurrency_safe: bool = False
    timeout_seconds: float | None = None
    min_start_window_seconds: float | None = None
    cancellation_grace_seconds: float | None = None
    completion_reserve_seconds: float | None = None
    max_result_bytes: int | None = 1_000_000
    metadata: dict[str, Any] = field(default_factory=dict)
    is_dangerous: bool = False
    requires_approval: bool = False
    max_attempts: int | None = None
    required_secret_names: list[str] = field(default_factory=list)
    version: str = "1.0.0"
    result_persistence: ToolResultPersistenceContract | dict[str, Any] = field(
        default_factory=ToolResultPersistenceContract
    )

    def __post_init__(self) -> None:
        if not self.name:
            raise ToolDefinitionError("tool name is required")
        if "." not in self.name or any(not segment for segment in self.name.split(".")):
            raise ToolDefinitionError(f"tool name must be namespaced: {self.name}")
        if not self.version:
            raise ToolDefinitionError(f"tool version is required for {self.name}")
        if self.min_start_window_seconds is not None:
            _validate_window_value(
                "min_start_window_seconds",
                self.min_start_window_seconds,
                tool_name=self.name,
            )
        if self.completion_reserve_seconds is not None:
            _validate_window_value(
                "completion_reserve_seconds",
                self.completion_reserve_seconds,
                tool_name=self.name,
            )
        if self.timeout_seconds is not None:
            _validate_window_value(
                "timeout_seconds",
                self.timeout_seconds,
                tool_name=self.name,
                positive=True,
            )
        if self.cancellation_grace_seconds is not None:
            _validate_window_value(
                "cancellation_grace_seconds",
                self.cancellation_grace_seconds,
                tool_name=self.name,
            )
        if (
            self.timeout_seconds is not None
            and self.min_start_window_seconds is not None
            and self.min_start_window_seconds > self.timeout_seconds
        ):
            raise ToolDefinitionError(
                "min_start_window_seconds must not exceed timeout_seconds "
                f"for {self.name}"
            )
        if self.max_attempts is not None and (
            type(self.max_attempts) is not int or self.max_attempts < 1
        ):
            raise ToolDefinitionError(
                f"max_attempts must be a positive integer for {self.name}"
            )
        if (
            self.max_result_bytes is not None
            and (not isinstance(self.max_result_bytes, int) or self.max_result_bytes < 0)
        ):
            raise ToolDefinitionError(
                f"max_result_bytes must be a non-negative integer for {self.name}"
            )
        if any(not isinstance(name, str) or not name for name in self.required_secret_names):
            raise ToolDefinitionError(f"required secret names must be non-empty strings for {self.name}")
        object.__setattr__(self, "input_schema", dict(self.input_schema or {}))
        object.__setattr__(
            self,
            "output_schema",
            dict(self.output_schema) if self.output_schema is not None else None,
        )
        object.__setattr__(self, "metadata", dict(self.metadata))
        object.__setattr__(self, "required_secret_names", list(self.required_secret_names))
        result_persistence = ToolResultPersistenceContract.from_any(
            self.result_persistence
        )
        result_persistence.validate_definition(
            tool_name=self.name,
            output_schema=self.output_schema,
        )
        object.__setattr__(self, "result_persistence", result_persistence)

    @property
    def namespace(self) -> str:
        return self.name.split(".", maxsplit=1)[0]

    def short_name(self) -> str:
        return self.name.split(".", maxsplit=1)[1]

    @property
    def tool_id(self) -> str:
        return f"{self.name}@{self.version}"

    @property
    def required_arguments(self) -> list[str]:
        required = self.input_schema.get("required", [])
        if not isinstance(required, list):
            raise ToolDefinitionError(f"required arguments must be a list for tool {self.name}")
        return [str(item) for item in required]

    @property
    def side_effect_value(self) -> str:
        return self.side_effect.value if isinstance(self.side_effect, ToolSideEffect) else str(self.side_effect)

    def to_dict(self) -> dict[str, Any]:
        return {
            "tool_id": self.tool_id,
            "name": self.name,
            "namespace": self.namespace,
            "short_name": self.short_name(),
            "version": self.version,
            "description": self.description,
            "input_schema": dict(self.input_schema),
            "output_schema": dict(self.output_schema) if self.output_schema is not None else None,
            "side_effect": self.side_effect_value,
            "is_dangerous": self.is_dangerous,
            "requires_approval": self.requires_approval,
            "timeout_seconds": self.timeout_seconds,
            "min_start_window_seconds": self.min_start_window_seconds,
            "cancellation_grace_seconds": self.cancellation_grace_seconds,
            "completion_reserve_seconds": self.completion_reserve_seconds,
            "max_attempts": self.max_attempts,
            "max_result_bytes": self.max_result_bytes,
            "concurrency_safe": self.concurrency_safe,
            "required_secret_names": list(self.required_secret_names),
            "metadata": dict(self.metadata),
            "result_persistence": self.result_persistence.to_dict(),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ToolDefinition":
        return cls(
            name=str(payload.get("name") or ""),
            description=str(payload.get("description") or ""),
            input_schema=dict(payload.get("input_schema") or {}),
            output_schema=(
                dict(payload["output_schema"])
                if isinstance(payload.get("output_schema"), dict)
                else None
            ),
            side_effect=str(payload.get("side_effect") or "none"),
            concurrency_safe=bool(payload.get("concurrency_safe", False)),
            timeout_seconds=payload.get("timeout_seconds"),
            min_start_window_seconds=payload.get("min_start_window_seconds"),
            cancellation_grace_seconds=payload.get(
                "cancellation_grace_seconds"
            ),
            completion_reserve_seconds=payload.get("completion_reserve_seconds"),
            max_result_bytes=payload.get("max_result_bytes", 1_000_000),
            metadata=dict(payload.get("metadata") or {}),
            is_dangerous=bool(payload.get("is_dangerous", False)),
            requires_approval=bool(payload.get("requires_approval", False)),
            max_attempts=payload.get("max_attempts"),
            required_secret_names=[str(item) for item in payload.get("required_secret_names", [])],
            version=str(payload.get("version") or "1.0.0"),
            result_persistence=payload.get("result_persistence"),
        )


def _validate_window_value(
    field_name: str,
    value: Any,
    *,
    tool_name: str,
    positive: bool = False,
) -> None:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(float(value))
        or (float(value) <= 0 if positive else float(value) < 0)
    ):
        condition = "positive" if positive else "non-negative"
        raise ToolDefinitionError(
            f"{field_name} must be a finite {condition} number for {tool_name}"
        )
