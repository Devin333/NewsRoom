from __future__ import annotations

from typing import Any


class ToolRetryController:
    def should_retry(self, attempt: int, max_attempts: int, error: Exception | None = None) -> bool:
        _ = error
        return attempt < max(1, int(max_attempts))

    def run_with_retry(self, fn: Any, *, max_attempts: int = 1) -> Any:
        last_error: Exception | None = None
        for attempt in range(1, max(1, int(max_attempts)) + 1):
            try:
                return fn()
            except Exception as exc:
                last_error = exc
                if not self.should_retry(attempt, max_attempts, exc):
                    raise
        if last_error is not None:
            raise last_error
        raise RuntimeError("retry loop exited unexpectedly")
