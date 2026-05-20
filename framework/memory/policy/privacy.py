from __future__ import annotations

from dataclasses import dataclass, field

from framework.memory.models import MemoryRecord


@dataclass(frozen=True)
class MemoryPrivacyPolicy:
    blocked_metadata_keys: set[str] = field(default_factory=lambda: {"api_key", "password", "secret", "token"})

    def validate(self, record: MemoryRecord) -> None:
        keys = {str(key).lower() for key in record.metadata} | {str(key).lower() for key in record.refs}
        blocked = sorted(key for key in keys if any(token in key for token in self.blocked_metadata_keys))
        if blocked:
            raise ValueError(f"memory record contains sensitive key: {blocked[0]}")
