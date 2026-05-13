from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Literal
from urllib.parse import urlsplit

from domain.sources import SourceDefinition, SourceReliability, SourceSelectionReport, SourceType


_RELIABILITY_SCORE = {
    SourceReliability.HIGH: 3,
    SourceReliability.MEDIUM: 2,
    SourceReliability.LOW: 1,
}
FETCHABLE_SOURCE_TYPES = {
    SourceType.RSS,
    SourceType.ATOM,
    SourceType.HTML,
    SourceType.OFFICIAL_BLOG,
    SourceType.WEB_PAGE,
    SourceType.ARXIV,
    SourceType.GITHUB,
    SourceType.HACKERNEWS,
    SourceType.REDDIT,
    SourceType.LOBSTERS,
    SourceType.STACKOVERFLOW,
    SourceType.DEVTO,
    SourceType.MEDIUM,
}
_SAFE_SOURCE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
_SENSITIVE_METADATA_KEY_PARTS = (
    "authorization",
    "cookie",
    "api_key",
    "apikey",
    "access_token",
    "refresh_token",
    "token",
    "secret",
    "password",
)


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
    def __init__(
        self,
        sources: list[SourceDefinition] | None = None,
        *,
        connectors: dict[str | SourceType, Any] | None = None,
    ) -> None:
        self._sources: dict[str, SourceDefinition] = {}
        self._connectors: dict[SourceType, Any] = {}
        for source in sources or []:
            self.register(source)
        for source_type, connector in (connectors or {}).items():
            self.register_connector(source_type, connector)

    def register(self, source: SourceDefinition) -> None:
        if source.source_id in self._sources:
            raise ValueError(f"source already registered: {source.source_id}")
        self._sources[source.source_id] = source

    def get(self, source_id: str) -> SourceDefinition:
        try:
            return self._sources[source_id]
        except KeyError as exc:
            raise KeyError(f"source is not registered: {source_id}") from exc

    def register_connector(self, source_type: str | SourceType, connector: Any) -> None:
        expected_type = SourceType(source_type)
        if connector is None:
            raise ValueError("connector is required")
        self._connectors[expected_type] = connector

    def get_connector(self, source_type: str | SourceType) -> Any:
        expected_type = SourceType(source_type)
        try:
            return self._connectors[expected_type]
        except KeyError as exc:
            raise KeyError(f"connector is not registered for source_type: {expected_type.value}") from exc

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

    def list_by_reliability(
        self,
        reliability: str | SourceReliability,
        *,
        enabled_only: bool = True,
    ) -> list[SourceDefinition]:
        expected_reliability = SourceReliability(reliability)
        return [
            source
            for source in self.list_sources(enabled_only=enabled_only)
            if source.reliability == expected_reliability
        ]

    def list_by_category(
        self,
        category: str,
        *,
        enabled_only: bool = True,
    ) -> list[SourceDefinition]:
        expected_category = _normalize_category(category)
        return [
            source
            for source in self.list_sources(enabled_only=enabled_only)
            if _normalize_category(source.category) == expected_category
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
        category: str | None = None,
        reliability: str | SourceReliability | None = None,
    ) -> list[SourceDefinition]:
        sources = self._filter_sources(
            enabled_only=enabled_only,
            language=language,
            region=region,
            category=category,
            reliability=reliability,
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
        category: str | None = None,
        reliability: str | SourceReliability | None = None,
        fallback_to_enabled: bool = True,
    ) -> list[SourceDefinition]:
        selected, _report = self.select_sources_with_report(
            topic=topic,
            enabled_only=enabled_only,
            language=language,
            region=region,
            category=category,
            reliability=reliability,
            fallback_to_enabled=fallback_to_enabled,
        )
        return selected

    def select_sources_with_report(
        self,
        *,
        topic: str,
        enabled_only: bool = True,
        language: str | None = None,
        region: str | None = None,
        category: str | None = None,
        reliability: str | SourceReliability | None = None,
        fallback_to_enabled: bool = True,
    ) -> tuple[list[SourceDefinition], SourceSelectionReport]:
        sources = self._filter_sources(
            enabled_only=enabled_only,
            language=language,
            region=region,
            category=category,
            reliability=reliability,
        )
        matched = [source for source in sources if _topic_match_score(source, topic) > 0]
        if matched or not fallback_to_enabled:
            selected = self._sort_for_topic(matched, topic)
            fallback_used = False
        else:
            selected = sources
            fallback_used = bool(selected)
        return selected, _selection_report(
            topic=topic,
            filters={
                "enabled_only": enabled_only,
                "language": language,
                "region": region,
                "category": category,
                "reliability": (
                    SourceReliability(reliability).value if reliability is not None else None
                ),
                "fallback_to_enabled": fallback_to_enabled,
            },
            matched_source_count=len(matched),
            selected=selected,
            fallback_used=fallback_used,
            fallback_reason="no_topic_match" if fallback_used else None,
        )

    def selection_report(
        self,
        *,
        topic: str,
        selected_sources: list[SourceDefinition],
        filters: dict[str, Any] | None = None,
        matched_source_count: int | None = None,
        fallback_used: bool = False,
        fallback_reason: str | None = None,
    ) -> SourceSelectionReport:
        return _selection_report(
            topic=topic,
            filters=filters or {},
            matched_source_count=(
                len(selected_sources) if matched_source_count is None else matched_source_count
            ),
            selected=selected_sources,
            fallback_used=fallback_used,
            fallback_reason=fallback_reason,
        )

    def _filter_sources(
        self,
        *,
        enabled_only: bool,
        language: str | None,
        region: str | None,
        category: str | None,
        reliability: str | SourceReliability | None,
    ) -> list[SourceDefinition]:
        sources = self.list_sources(enabled_only=enabled_only)
        if language is not None:
            sources = [source for source in sources if source.language == language]
        if region is not None:
            sources = [source for source in sources if source.region == region]
        if category is not None:
            expected_category = _normalize_category(category)
            sources = [
                source
                for source in sources
                if _normalize_category(source.category) == expected_category
            ]
        if reliability is not None:
            expected_reliability = SourceReliability(reliability)
            sources = [source for source in sources if source.reliability == expected_reliability]
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


def _selection_report(
    *,
    topic: str,
    filters: dict[str, Any],
    matched_source_count: int,
    selected: list[SourceDefinition],
    fallback_used: bool,
    fallback_reason: str | None,
) -> SourceSelectionReport:
    return SourceSelectionReport(
        topic=topic,
        selected_source_count=len(selected),
        matched_source_count=matched_source_count,
        fallback_used=fallback_used,
        fallback_reason=fallback_reason,
        selected_source_ids=[source.source_id for source in selected],
        selected_sources=[_source_summary(source) for source in selected],
        filters={key: value for key, value in filters.items() if value is not None},
    )


def _source_summary(source: SourceDefinition) -> dict[str, Any]:
    return {
        "source_id": source.source_id,
        "source_name": source.name,
        "source_type": source.source_type.value,
        "url": source.url,
        "reliability": source.reliability.value,
        "authority_score": source.authority_score,
        "enabled": source.enabled,
        "fetch_interval_seconds": source.fetch_interval_seconds,
        "respect_robots": source.respect_robots,
        "user_agent": source.user_agent,
        "topics": list(source.topics),
        "category": source.category,
        "language": source.language,
        "region": source.region,
    }


def _validate_source(source: SourceDefinition) -> list[SourceRegistryValidationIssue]:
    issues: list[SourceRegistryValidationIssue] = []
    if _SAFE_SOURCE_ID_RE.fullmatch(source.source_id) is None:
        issues.append(
            SourceRegistryValidationIssue(
                severity="error",
                source_id=source.source_id,
                field="source_id",
                message="source_id must be path-safe: letters, numbers, dot, underscore, and hyphen only",
            )
        )
    if source.authority_score < 0.0 or source.authority_score > 1.0:
        issues.append(
            SourceRegistryValidationIssue(
                severity="error",
                source_id=source.source_id,
                field="authority_score",
                message="authority_score must be between 0.0 and 1.0",
            )
        )
    if source.fetch_interval_seconds < 1:
        issues.append(
            SourceRegistryValidationIssue(
                severity="error",
                source_id=source.source_id,
                field="fetch_interval_seconds",
                message="fetch_interval_seconds must be at least 1",
            )
        )
    if source.user_agent is not None and not str(source.user_agent).strip():
        issues.append(
            SourceRegistryValidationIssue(
                severity="error",
                source_id=source.source_id,
                field="user_agent",
                message="user_agent must not be blank",
            )
        )
    scheme = urlsplit(source.url).scheme.casefold()
    if scheme == "fixture":
        issues.append(
            SourceRegistryValidationIssue(
                severity="error",
                source_id=source.source_id,
                field="url",
                message="fixture URLs are not allowed in registered sources",
            )
        )
    if source.source_type in FETCHABLE_SOURCE_TYPES:
        if scheme not in {"http", "https"}:
            issues.append(
                SourceRegistryValidationIssue(
                    severity="error",
                    source_id=source.source_id,
                    field="url",
                    message="fetchable source URL must use http or https",
                )
            )
    sensitive_metadata_paths = _sensitive_metadata_paths(source.metadata)
    for path in sensitive_metadata_paths:
        issues.append(
            SourceRegistryValidationIssue(
                severity="error",
                source_id=source.source_id,
                field=f"metadata.{path}",
                message="source metadata must not contain secrets or credentials",
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


def _sensitive_metadata_paths(value: Any, *, prefix: str = "") -> list[str]:
    if isinstance(value, dict):
        paths: list[str] = []
        for key, item in value.items():
            key_text = str(key)
            current_path = f"{prefix}.{key_text}" if prefix else key_text
            if _is_sensitive_metadata_key(key_text):
                paths.append(current_path)
                continue
            paths.extend(_sensitive_metadata_paths(item, prefix=current_path))
        return paths
    if isinstance(value, list):
        paths = []
        for index, item in enumerate(value):
            current_path = f"{prefix}[{index}]" if prefix else f"[{index}]"
            paths.extend(_sensitive_metadata_paths(item, prefix=current_path))
        return paths
    return []


def _is_sensitive_metadata_key(key: str) -> bool:
    normalized = key.replace("-", "_").casefold()
    return any(part in normalized for part in _SENSITIVE_METADATA_KEY_PARTS)


def _topic_terms(topic: str) -> set[str]:
    return {term for term in _normalize_topic(topic).split() if term}


def _normalize_topic(topic: str) -> str:
    return " ".join(topic.casefold().replace("-", " ").replace("_", " ").split())


def _normalize_category(category: str | None) -> str | None:
    if category is None:
        return None
    return " ".join(str(category).casefold().replace("-", " ").replace("_", " ").split())
