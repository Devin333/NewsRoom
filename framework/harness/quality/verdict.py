from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from framework.harness.control_plane.errors import HarnessValidationError
from framework.shared.json import to_jsonable


@dataclass(frozen=True)
class HarnessQualityVerdict:
    passed: bool
    score: float | None = None
    issues: tuple[str, ...] = ()
    repair_hints: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.score is not None and not 0 <= self.score <= 1:
            raise HarnessValidationError("score must be between 0 and 1")
        object.__setattr__(self, "issues", tuple(str(issue) for issue in self.issues))
        object.__setattr__(self, "repair_hints", tuple(str(hint) for hint in self.repair_hints))
        object.__setattr__(self, "metadata", dict(self.metadata))

    def to_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "score": self.score,
            "issues": list(self.issues),
            "repair_hints": list(self.repair_hints),
            "metadata": to_jsonable(self.metadata),
        }


__all__ = ["HarnessQualityVerdict"]
