from __future__ import annotations

from collections import deque

from core.framework.llm.models import LLMRequest, LLMResponse, TokenUsage


class FakeLLMClient:
    def __init__(
        self,
        scripted_responses: list[str | LLMResponse],
        *,
        input_tokens_per_call: int = 12,
        output_tokens_per_call: int = 8,
    ) -> None:
        if not scripted_responses:
            raise ValueError("FakeLLMClient requires at least one scripted response")
        self._responses = deque(scripted_responses)
        self._input_tokens_per_call = input_tokens_per_call
        self._output_tokens_per_call = output_tokens_per_call
        self.requests: list[LLMRequest] = []

    @property
    def call_count(self) -> int:
        return len(self.requests)

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
