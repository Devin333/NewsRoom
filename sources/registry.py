from __future__ import annotations

from dataclasses import dataclass
from typing import Literal
from urllib.parse import urlsplit

from domain.sources import SourceDefinition, SourceReliability, SourceType


_RELIABILITY_SCORE = {
    SourceReliability.HIGH: 3,
    SourceReliability.MEDIUM: 2,
    SourceReliability.LOW: 1,
}
FETCHABLE_SOURCE_TYPES = {
    SourceType.RSS,
    SourceType.ATOM,
    SourceType.HTML,
    SourceType.ARXIV,
    SourceType.GITHUB,
}


@dataclass(frozen=True)
class SourceRegistryValidationIssue:
    severity: Literal["error", "warning"]
    source_id: str
    field: str
    message: str

    def to_dict(self) -> dict[str, str]:
        return {
            "severity": self.severity,
            "source_id": self.source_id,
            "field": self.field,
            "message": self.message,
        }


@dataclass(frozen=True)
class SourceRegistryValidationResult:
    issues: list[SourceRegistryValidationIssue]

    @property
    def is_valid(self) -> bool:
        return not any(issue.severity == "error" for issue in self.issues)

    @property
    def errors(self) -> list[SourceRegistryValidationIssue]:
        return [issue for issue in self.issues if issue.severity == "error"]

    @property
    def warnings(self) -> list[SourceRegistryValidationIssue]:
        return [issue for issue in self.issues if issue.severity == "warning"]

    def to_dict(self) -> dict[str, object]:
        return {
            "is_valid": self.is_valid,
            "error_count": len(self.errors),
            "warning_count": len(self.warnings),
            "issues": [issue.to_dict() for issue in self.issues],
        }


class SourceRegistry:
    def __init__(self, sources: list[SourceDefinition] | None = None) -> None:
        self._sources: dict[str, SourceDefinition] = {}
        for source in sources or []:
            self.register(source)

    def register(self, source: SourceDefinition) -> None:
        if source.source_id in self._sources:
            raise ValueError(f"source already registered: {source.source_id}")
        self._sources[source.source_id] = source

    def get(self, source_id: str) -> SourceDefinition:
        try:
            return self._sources[source_id]
        except KeyError as exc:
            raise KeyError(f"source is not registered: {source_id}") from exc

    def list_sources(self, *, enabled_only: bool = True) -> list[SourceDefinition]:
        sources = list(self._sources.values())
        if enabled_only:
            sources = [source for source in sources if source.enabled]
        return sorted(sources, key=lambda source: source.source_id)

    def list_by_type(
        self,
        source_type: str | SourceType,
        *,
        enabled_only: bool = True,
    ) -> list[SourceDefinition]:
        expected_type = SourceType(source_type)
        return [
            source
            for source in self.list_sources(enabled_only=enabled_only)
            if source.source_type == expected_type
        ]

    def validate(self) -> SourceRegistryValidationResult:
        issues: list[SourceRegistryValidationIssue] = []
        for source in self.list_sources(enabled_only=False):
            issues.extend(_validate_source(source))
        return SourceRegistryValidationResult(issues=issues)

    def list_by_topic(
        self,
        topic: str,
        *,
        enabled_only: bool = True,
        language: str | None = None,
        region: str | None = None,
    ) -> list[SourceDefinition]:
        sources = self._filter_sources(
            enabled_only=enabled_only,
            language=language,
            region=region,
        )
        matched = [source for source in sources if _topic_match_score(source, topic) > 0]
        return self._sort_for_topic(matched, topic)

    def select_sources(
        self,
        *,
        topic: str,
        enabled_only: bool = True,
        language: str | None = None,
        region: str | None = None,
        fallback_to_enabled: bool = True,
    ) -> list[SourceDefinition]:
        sources = self._filter_sources(
            enabled_only=enabled_only,
            language=language,
            region=region,
        )
        matched = [source for source in sources if _topic_match_score(source, topic) > 0]
        if matched or not fallback_to_enabled:
            return self._sort_for_topic(matched, topic)
        return sources

    def _filter_sources(
        self,
        *,
        enabled_only: bool,
        language: str | None,
        region: str | None,
    ) -> list[SourceDefinition]:
        sources = self.list_sources(enabled_only=enabled_only)
        if language is not None:
            sources = [source for source in sources if source.language == language]
        if region is not None:
            sources = [source for source in sources if source.region == region]
        return sources

    def _sort_for_topic(self, sources: list[SourceDefinition], topic: str) -> list[SourceDefinition]:
        return sorted(
            sources,
            key=lambda source: (
                -_topic_match_score(source, topic),
                -_RELIABILITY_SCORE[source.reliability],
                -source.authority_score,
                source.source_id,
            ),
        )


def _topic_match_score(source: SourceDefinition, requested_topic: str) -> int:
    source_topics = {_normalize_topic(topic) for topic in source.topics if topic}
    if not source_topics:
        return 0
    request_terms = _topic_terms(requested_topic)
    score = 0
    for source_topic in source_topics:
        if source_topic in request_terms or source_topic in _normalize_topic(requested_topic):
            score += 2
            continue
        topic_terms = _topic_terms(source_topic)
        if topic_terms and topic_terms.intersection(request_terms):
            score += 1
    return score


def _validate_source(source: SourceDefinition) -> list[SourceRegistryValidationIssue]:
    issues: list[SourceRegistryValidationIssue] = []
    if source.authority_score < 0.0 or source.authority_score > 1.0:
        issues.append(
            SourceRegistryValidationIssue(
                severity="error",
                source_id=source.source_id,
                field="authority_score",
                message="authority_score must be between 0.0 and 1.0",
            )
        )
    if source.source_type in FETCHABLE_SOURCE_TYPES:
        scheme = urlsplit(source.url).scheme.casefold()
        if scheme not in {"http", "https"}:
            issues.append(
                SourceRegistryValidationIssue(
                    severity="error",
                    source_id=source.source_id,
                    field="url",
                    message="fetchable source URL must use http or https",
                )
            )
    if not source.topics:
        issues.append(
            SourceRegistryValidationIssue(
                severity="warning",
                source_id=source.source_id,
                field="topics",
                message="source has no topic metadata",
            )
        )
    return issues


def _topic_terms(topic: str) -> set[str]:
    return {term for term in _normalize_topic(topic).split() if term}


def _normalize_topic(topic: str) -> str:
    return " ".join(topic.casefold().replace("-", " ").replace("_", " ").split())
