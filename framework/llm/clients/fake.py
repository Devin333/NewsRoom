from __future__ import annotations

from collections import deque
from dataclasses import replace
from collections.abc import Iterable

from framework.llm.models.request import LLMRequest
from framework.llm.models.response import LLMResponse
from framework.llm.models.stream import LLMStreamEvent
from framework.llm.models.usage import TokenUsage


class FakeLLMClient:
    def __init__(
        self,
        scripted_responses: list[str | LLMResponse] | None = None,
        *,
        responses: list[str | LLMResponse] | None = None,
        input_tokens_per_call: int = 12,
        output_tokens_per_call: int = 8,
    ) -> None:
        initial_responses = scripted_responses if scripted_responses is not None else responses
        self._responses = deque(initial_responses or [])
        self._input_tokens_per_call = input_tokens_per_call
        self._output_tokens_per_call = output_tokens_per_call
        self.requests: list[LLMRequest] = []

    @property
    def call_count(self) -> int:
        return len(self.requests)

    def calls(self) -> list[LLMRequest]:
        return list(self.requests)

    def push_response(self, response: str | LLMResponse) -> None:
        self._responses.append(response)

    def complete(self, request: LLMRequest) -> LLMResponse:
        self.requests.append(request)
        if not self._responses:
            raise RuntimeError("FakeLLMClient has no scripted responses remaining")

        response = self._responses.popleft()
        if isinstance(response, LLMResponse):
            return _bind_response_identity(response, request)
        return LLMResponse(
            content=response,
            usage=TokenUsage(
                input_tokens=self._input_tokens_per_call,
                output_tokens=self._output_tokens_per_call,
            ),
            metadata={"provider": "fake", "model": "fake-llm"},
            execution_identity=request.execution_identity,
        )

    def stream(self, request: LLMRequest) -> Iterable[LLMStreamEvent]:
        response = self.complete(request)
        provisional = request.output_schema is not None
        yield LLMStreamEvent(
            event_type="message_start",
            metadata={
                "provider": "fake",
                "model": response.model or "fake-llm",
                "provisional": provisional,
            },
            execution_identity=request.execution_identity,
        )
        if response.content:
            yield LLMStreamEvent(
                event_type="text_delta",
                text_delta=response.content,
                metadata={"provisional": provisional},
                execution_identity=request.execution_identity,
            )
        for tool_call in response.tool_calls:
            yield LLMStreamEvent(
                event_type="tool_call_complete",
                tool_call=tool_call,
                metadata={"provisional": provisional},
                execution_identity=request.execution_identity,
            )
        yield LLMStreamEvent(
            event_type="usage_delta",
            usage_delta=response.usage,
            metadata={"provisional": provisional},
            execution_identity=request.execution_identity,
        )
        yield LLMStreamEvent(
            event_type="message_complete",
            structured_output=response.structured_output,
            metadata={**response.metadata, "provisional": False},
            execution_identity=request.execution_identity,
        )


def _bind_response_identity(response: LLMResponse, request: LLMRequest) -> LLMResponse:
    if response.execution_identity is None:
        return replace(response, execution_identity=request.execution_identity)
    if request.execution_identity is not None and response.execution_identity != request.execution_identity:
        raise ValueError("LLM response execution identity does not match request")
    return response

