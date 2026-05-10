from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from evidence import EvidenceBundle


@dataclass(frozen=True)
class SectionSupport:
    section_title: str
    cited_urls: list[str]
    matched_evidence_ids: list[str]
    supported: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "section_title": self.section_title,
            "cited_urls": list(self.cited_urls),
            "matched_evidence_ids": list(self.matched_evidence_ids),
            "supported": self.supported,
        }


@dataclass(frozen=True)
class SupportMatrix:
    sections: list[SectionSupport] = field(default_factory=list)

    @property
    def unsupported_sections(self) -> list[SectionSupport]:
        return [section for section in self.sections if not section.supported]

    @property
    def coverage_ratio(self) -> float:
        if not self.sections:
            return 0.0
        supported_count = sum(1 for section in self.sections if section.supported)
        return supported_count / len(self.sections)

    def to_dict(self) -> dict[str, Any]:
        return {
            "sections": [section.to_dict() for section in self.sections],
            "coverage_ratio": self.coverage_ratio,
            "unsupported_sections": [
                section.section_title for section in self.unsupported_sections
            ],
        }


class SupportMatrixBuilder:
    def build(self, report: dict, evidence_bundle: EvidenceBundle) -> SupportMatrix:
        evidence_by_url = {item.source_url: item.evidence_id for item in evidence_bundle.items}
        sections = []
        for section in report.get("sections", []):
            cited_urls = _section_sources(section)
            matched = [evidence_by_url[url] for url in cited_urls if url in evidence_by_url]
            sections.append(
                SectionSupport(
                    section_title=str(section.get("title", "Untitled")),
                    cited_urls=cited_urls,
                    matched_evidence_ids=matched,
                    supported=bool(matched),
                )
            )
        return SupportMatrix(sections=sections)


def _section_sources(section: dict) -> list[str]:
    sources = section.get("sources") or section.get("source_urls") or []
    if isinstance(sources, str):
        return [sources]
    if isinstance(sources, list):
        return [source for source in sources if isinstance(source, str)]
    return []
