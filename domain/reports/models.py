from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class FinalReport:
    title: str
    sections: list[dict[str, Any]]
    source_urls: list[str]
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "sections": [dict(section) for section in self.sections],
            "source_urls": list(self.source_urls),
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class BlockedReport:
    title: str
    reasons: list[str]
    draft: dict[str, Any]
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "reasons": list(self.reasons),
            "draft": dict(self.draft),
            "metadata": dict(self.metadata),
        }
