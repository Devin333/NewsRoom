from __future__ import annotations

from collections.abc import Iterable
from typing import Protocol

from framework.llm.models.request import LLMRequest
from framework.llm.models.response import LLMResponse
from framework.llm.models.stream import LLMStreamEvent


class LLMClient(Protocol):
    def complete(self, request: LLMRequest) -> LLMResponse:
        ...

    def stream(self, request: LLMRequest) -> Iterable[LLMStreamEvent]:
        ...
