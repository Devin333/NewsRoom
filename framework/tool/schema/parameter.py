from __future__ import annotations

import inspect
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class ToolParameterType(str, Enum):
    STRING = "string"
    INTEGER = "integer"
    NUMBER = "number"
    BOOLEAN = "boolean"
    OBJECT = "object"
    ARRAY = "array"
    NULL = "null"


@dataclass(frozen=True)
class ToolParameter:
    name: str
    type: ToolParameterType | str = ToolParameterType.STRING
    description: str = ""
    required: bool = True
    default: Any = inspect._empty
    enum: list[Any] | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_json_schema(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"type": self.type.value if isinstance(self.type, ToolParameterType) else str(self.type)}
        if self.description:
            payload["description"] = self.description
        if self.default is not inspect._empty:
            payload["default"] = self.default
        if self.enum is not None:
            payload["enum"] = list(self.enum)
        payload.update(dict(self.metadata))
        return payload

    @classmethod
    def from_signature_parameter(cls, parameter: inspect.Parameter) -> "ToolParameter":
        annotation = parameter.annotation
        return cls(
            name=parameter.name,
            type=_json_type_from_annotation(annotation),
            required=parameter.default is inspect._empty,
            default=parameter.default,
        )


def _json_type_from_annotation(annotation: Any) -> ToolParameterType:
    if annotation in {str, inspect._empty}:
        return ToolParameterType.STRING
    if annotation is int:
        return ToolParameterType.INTEGER
    if annotation is float:
        return ToolParameterType.NUMBER
    if annotation is bool:
        return ToolParameterType.BOOLEAN
    if annotation in {dict, Any}:
        return ToolParameterType.OBJECT
    if annotation is list:
        return ToolParameterType.ARRAY
    return ToolParameterType.STRING
