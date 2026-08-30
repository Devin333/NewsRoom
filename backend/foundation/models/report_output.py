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

def render_markdown(report: FinalReport) -> str:
    lines = [f"# {report.title}", ""]
    for section in report.sections:
        lines.extend([f"## {section['title']}", str(section["content"]), ""])
    if report.source_urls:
        lines.extend(["## Sources", *[f"- {url}" for url in report.source_urls], ""])
    return "\n".join(lines)
