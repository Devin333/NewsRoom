from __future__ import annotations

import json
from math import ceil

from framework.llm.models.request import LLMRequest


def estimate_request_tokens(request: LLMRequest) -> int:
    payload = {
        "messages": request.messages,
        "tools": request.tools,
        "response_format": request.response_format,
        "output_schema": request.output_schema,
    }
    serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return max(1, ceil(len(serialized) / 4))

