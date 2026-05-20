from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

from framework.llm.models.request import LLMRequest


@dataclass(frozen=True)
class LLMCacheKey:
    provider: str
    model: str
    digest: str

    @classmethod
    def from_request(cls, *, provider: str, model: str, request: LLMRequest) -> LLMCacheKey:
        payload = {
            "provider": provider,
            "model": model,
            "request": request.to_dict(redact=False),
        }
        encoded = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode(
            "utf-8"
        )
        return cls(provider=provider, model=model, digest=hashlib.sha256(encoded).hexdigest())

    def to_string(self) -> str:
        return f"{self.provider}:{self.model}:{self.digest}"

