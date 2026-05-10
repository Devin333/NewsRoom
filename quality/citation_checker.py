from __future__ import annotations

from dataclasses import dataclass, field

from evidence.models import EvidenceBundle


@dataclass(frozen=True)
class CitationCheckResult:
    passed: bool
    cited_urls: list[str] = field(default_factory=list)
    unknown_urls: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "passed": self.passed,
            "cited_urls": list(self.cited_urls),
            "unknown_urls": list(self.unknown_urls),
        }


class CitationChecker:
    def check(self, report: dict, evidence_bundle: EvidenceBundle) -> CitationCheckResult:
        cited_urls = sorted(_collect_cited_urls(report))
        allowed_urls = evidence_bundle.source_urls
        unknown_urls = sorted(url for url in cited_urls if url not in allowed_urls)
        return CitationCheckResult(
            passed=not unknown_urls,
            cited_urls=cited_urls,
            unknown_urls=unknown_urls,
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
