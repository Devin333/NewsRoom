from __future__ import annotations

from dataclasses import dataclass, field

from evidence.models import EvidenceBundle


@dataclass(frozen=True)
class CitationCheckResult:
    passed: bool
    cited_urls: list[str] = field(default_factory=list)
    unknown_urls: list[str] = field(default_factory=list)
    missing_section_sources: list[str] = field(default_factory=list)
    citation_coverage_score: float = 0.0

    def to_dict(self) -> dict:
        return {
            "passed": self.passed,
            "cited_urls": list(self.cited_urls),
            "unknown_urls": list(self.unknown_urls),
            "missing_section_sources": list(self.missing_section_sources),
            "citation_coverage_score": self.citation_coverage_score,
        }


class CitationChecker:
    def check(self, report: dict, evidence_bundle: EvidenceBundle) -> CitationCheckResult:
        cited_urls = sorted(_collect_cited_urls(report))
        allowed_urls = evidence_bundle.source_urls
        unknown_urls = sorted(url for url in cited_urls if url not in allowed_urls)
        missing_section_sources = _missing_section_sources(report)
        return CitationCheckResult(
            passed=not unknown_urls and not missing_section_sources,
            cited_urls=cited_urls,
            unknown_urls=unknown_urls,
            missing_section_sources=missing_section_sources,
            citation_coverage_score=_citation_coverage_score(report, missing_section_sources),
        )


def _collect_cited_urls(value) -> set[str]:
    urls: set[str] = set()
    if isinstance(value, dict):
        for key, item in value.items():
            if key in {"source_url", "url"} and isinstance(item, str):
                urls.add(item)
            elif key in {"source_urls", "sources"} and isinstance(item, list):
                urls.update(url for url in item if isinstance(url, str))
            else:
                urls.update(_collect_cited_urls(item))
    elif isinstance(value, list):
        for item in value:
            urls.update(_collect_cited_urls(item))
    return urls


def _missing_section_sources(report: dict) -> list[str]:
    missing = []
    for section in report.get("sections", []):
        if not _section_sources(section):
            missing.append(str(section.get("title", "Untitled")))
    return missing


def _citation_coverage_score(report: dict, missing_section_sources: list[str]) -> float:
    sections = report.get("sections", [])
    if not sections:
        return 0.0
    covered_count = max(0, len(sections) - len(missing_section_sources))
    return round(covered_count / len(sections), 4)


def _section_sources(section: dict) -> list[str]:
    sources = section.get("sources") or section.get("source_urls") or []
    if isinstance(sources, str):
        return [sources]
    if isinstance(sources, list):
        return [source for source in sources if isinstance(source, str)]
    return []
