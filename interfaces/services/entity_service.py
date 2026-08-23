from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from interfaces.services.report_service import ReportApplicationService
from infrastructure.storage.entities import EntityKind, LocalJsonTrackedEntityStore, TrackedEntity


DEFAULT_ENTITY_STORE_PATH = ".newsroom/entities/entities.json"


class TrackedEntityStore(Protocol):
    def list_entities(
        self,
        *,
        enabled_only: bool = False,
        kind: EntityKind | str | None = None,
    ) -> list[TrackedEntity]: ...

    def get_entity(self, entity_id: str) -> TrackedEntity: ...

    def upsert_entity(self, entity: TrackedEntity) -> TrackedEntity: ...

    def set_enabled(self, entity_id: str, *, enabled: bool) -> TrackedEntity: ...

    def delete_entity(self, entity_id: str) -> bool: ...


@dataclass(frozen=True)
class TrackedEntityListResult:
    entities: list[TrackedEntity]

    def to_dict(self) -> dict[str, Any]:
        return {
            "entity_count": len(self.entities),
            "entities": [entity.to_dict() for entity in self.entities],
        }


@dataclass(frozen=True)
class EntityReportMatch:
    report_id: str
    run_id: str
    title: str | None
    finished_at: str
    graph_id: str | None
    graph_version: str | None
    matched_aliases: list[str]
    match_count: int
    quality_score: float | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "report_id": self.report_id,
            "run_id": self.run_id,
            "title": self.title,
            "finished_at": self.finished_at,
            "graph_id": self.graph_id,
            "graph_version": self.graph_version,
            "matched_aliases": list(self.matched_aliases),
            "match_count": self.match_count,
            "quality_score": self.quality_score,
        }


@dataclass(frozen=True)
class EntityReportMatchResult:
    entity: TrackedEntity
    matches: list[EntityReportMatch]
    limit: int
    graph_id: str | None
    graph_ids: tuple[str, ...] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "entity": self.entity.to_dict(),
            "limit": self.limit,
            "graph_id": self.graph_id,
            "graph_ids": list(self.graph_ids) if self.graph_ids is not None else None,
            "match_count": len(self.matches),
            "matches": [match.to_dict() for match in self.matches],
        }


class EntityTrackingApplicationService:
    def __init__(
        self,
        store: TrackedEntityStore | None = None,
        *,
        store_path: str | Path = DEFAULT_ENTITY_STORE_PATH,
        report_service_factory: Any | None = None,
    ) -> None:
        self.store = store or LocalJsonTrackedEntityStore(store_path)
        self.report_service_factory = report_service_factory or ReportApplicationService

    def create_entity(
        self,
        *,
        name: str,
        kind: EntityKind | str = EntityKind.COMPANY,
        aliases: list[str] | None = None,
        entity_id: str | None = None,
        enabled: bool = True,
        metadata: dict[str, Any] | None = None,
    ) -> TrackedEntity:
        actual_kind = EntityKind(kind)
        entity = TrackedEntity(
            entity_id=entity_id or _entity_id(name=name, kind=actual_kind),
            name=name,
            kind=actual_kind,
            aliases=aliases or [],
            enabled=enabled,
            metadata=metadata or {},
        )
        return self.store.upsert_entity(entity)

    def list_entities(
        self,
        *,
        enabled_only: bool = False,
        kind: EntityKind | str | None = None,
    ) -> TrackedEntityListResult:
        return TrackedEntityListResult(
            entities=self.store.list_entities(enabled_only=enabled_only, kind=kind)
        )

    def set_enabled(self, entity_id: str, *, enabled: bool) -> TrackedEntity:
        return self.store.set_enabled(entity_id, enabled=enabled)

    def delete_entity(self, entity_id: str) -> bool:
        return self.store.delete_entity(entity_id)

    def match_reports(
        self,
        entity_id: str,
        *,
        artifact_root: str | Path = ".newsroom/runs",
        limit: int = 20,
        graph_id: str | None = None,
        graph_ids: tuple[str, ...] | None = None,
    ) -> EntityReportMatchResult:
        if limit <= 0:
            raise ValueError("limit must be greater than zero")
        entity = self.store.get_entity(entity_id)
        report_service = self.report_service_factory(artifact_root=artifact_root)
        candidate_set = report_service.list_reports(
            limit=max(limit * 5, limit),
            graph_id=graph_id,
            graph_ids=graph_ids,
        )
        matches: list[EntityReportMatch] = []
        for candidate in candidate_set.reports:
            detail = report_service.get_report(candidate.report_id)
            match = _match_report(entity, candidate, detail)
            if match is not None:
                matches.append(match)
            if len(matches) >= limit:
                break
        return EntityReportMatchResult(
            entity=entity,
            matches=matches,
            limit=limit,
            graph_id=graph_id,
            graph_ids=graph_ids,
        )


def _match_report(entity: TrackedEntity, candidate: Any, detail: Any) -> EntityReportMatch | None:
    aliases = [entity.name, *entity.aliases]
    haystack = _report_haystack(detail)
    matched_aliases = []
    match_count = 0
    for alias in aliases:
        normalized_alias = alias.casefold()
        count = haystack.count(normalized_alias)
        if count > 0:
            matched_aliases.append(alias)
            match_count += count
    if not matched_aliases:
        return None
    return EntityReportMatch(
        report_id=candidate.report_id,
        run_id=candidate.run_id,
        title=candidate.title,
        finished_at=candidate.finished_at,
        graph_id=getattr(candidate, "graph_id", None),
        graph_version=getattr(candidate, "graph_version", None),
        matched_aliases=matched_aliases,
        match_count=match_count,
        quality_score=candidate.quality_score,
    )


def _report_haystack(detail: Any) -> str:
    parts = [
        detail.title or "",
        json.dumps(detail.report_json or {}, ensure_ascii=False, sort_keys=True),
        detail.report_markdown or "",
    ]
    return " ".join(parts).casefold()


def _entity_id(*, name: str, kind: EntityKind) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    if not normalized:
        normalized = "entity"
    normalized = normalized[:48].strip("-") or "entity"
    digest = hashlib.sha256(f"{kind.value}:{name}".encode("utf-8")).hexdigest()[:8]
    return f"{kind.value}:{normalized}:{digest}"
