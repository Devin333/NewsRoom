from __future__ import annotations

from enum import Enum
from typing import Any


class MemoryKind(str, Enum):
    WORKING = "working"
    SESSION = "session"
    CORE = "core"
    EPISODIC = "episodic"
    SEMANTIC = "semantic"
    RELATION = "relation"
    REFLECTIVE = "reflective"
    PROCEDURAL = "procedural"
    ARTIFACT = "artifact"
    OBSERVATION = "observation"
    PREFERENCE = "preference"
    CONSTRAINT = "constraint"
    PLAN = "plan"
    DECISION = "decision"

    @classmethod
    def default(cls) -> "MemoryKind":
        return cls.SEMANTIC

    @classmethod
    def from_value(cls, value: Any) -> "MemoryKind":
        if isinstance(value, cls):
            return value
        return cls(str(value))

    def is_long_term_candidate(self) -> bool:
        return self in {
            MemoryKind.CORE,
            MemoryKind.SEMANTIC,
            MemoryKind.REFLECTIVE,
            MemoryKind.PROCEDURAL,
            MemoryKind.PREFERENCE,
            MemoryKind.CONSTRAINT,
            MemoryKind.DECISION,
        }

    def is_short_lived(self) -> bool:
        return self in {
            MemoryKind.WORKING,
            MemoryKind.SESSION,
            MemoryKind.OBSERVATION,
        }
