from __future__ import annotations

from typing import Any


class RetryController:
    def should_retry(self, attempt: int, error: Exception | None = None, policy: Any | None = None) -> bool:
        max_retries = int(getattr(policy, "max_retries", 0) if policy is not None else 0)
        _ = error
        return attempt <= max_retries


