from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from pydantic import Field

from business.foundation.context import AnalysisContext
from business.foundation.primitives import PrimitiveModel


class BusinessLLMRequest(PrimitiveModel):
    prompt: str
    output_schema: dict[str, Any] | None = Field(default=None, alias="schema")
    context: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)


class BusinessLLMResult(PrimitiveModel):
    content: str | None = None
    structured: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)


@runtime_checkable
class LLMPort(Protocol):
    def structured_output(self, *, prompt: str, schema: dict[str, Any], context: AnalysisContext) -> dict[str, Any]: ...


@runtime_checkable
class LLMGateway(Protocol):
    def complete(self, request: BusinessLLMRequest) -> BusinessLLMResult: ...


__all__ = ["BusinessLLMRequest", "BusinessLLMResult", "LLMGateway", "LLMPort"]
