from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class BackpressurePolicy:
    max_pending_per_queue: int | None = None

    def should_reject(self, *, pending_count: int) -> bool:
        return (
            self.max_pending_per_queue is not None
            and pending_count >= self.max_pending_per_queue
        )

    def should_accept(self, *, pending_count: int) -> bool:
        return not self.should_reject(pending_count=pending_count)

    def rejection_reason(self, *, pending_count: int) -> str | None:
        if self.should_reject(pending_count=pending_count):
            return "backpressure"
        return None

    def to_dict(self) -> dict[str, int | None]:
        return {"max_pending_per_queue": self.max_pending_per_queue}
