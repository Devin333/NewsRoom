from __future__ import annotations

from collections import deque
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
            return response
        return LLMResponse(
            content=response,
            usage=TokenUsage(
                input_tokens=self._input_tokens_per_call,
                output_tokens=self._output_tokens_per_call,
            ),
            metadata={"provider": "fake", "model": "fake-llm"},
        )

    def stream(self, request: LLMRequest) -> Iterable[LLMStreamEvent]:
        response = self.complete(request)
        yield LLMStreamEvent(
            event_type="message_start",
            metadata={"provider": "fake", "model": response.model or "fake-llm"},
        )
        if response.content:
            yield LLMStreamEvent(event_type="text_delta", text_delta=response.content)
        for tool_call in response.tool_calls:
            yield LLMStreamEvent(event_type="tool_call_complete", tool_call=tool_call)
        yield LLMStreamEvent(event_type="usage_delta", usage_delta=response.usage)
        yield LLMStreamEvent(event_type="message_complete", metadata=response.metadata)

