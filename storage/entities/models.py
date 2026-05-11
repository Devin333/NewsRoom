from __future__ import annotations

import re
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from enum import Enum
from typing import Any


class EntityKind(str, Enum):
    COMPANY = "company"
    PROJECT = "project"
    PERSON = "person"
    ORGANIZATION = "organization"


class TrackedEntityNotFoundError(KeyError):
    def __init__(self, entity_id: str) -> None:
        super().__init__(f"tracked entity not found: {entity_id}")
        self.entity_id = entity_id


@dataclass(frozen=True)
class TrackedEntity:
    entity_id: str
    name: str
    kind: EntityKind | str = EntityKind.COMPANY
    aliases: list[str] = field(default_factory=list)
    enabled: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def __post_init__(self) -> None:
        object.__setattr__(self, "entity_id", _validate_id(self.entity_id))
        name = self.name.strip()
        if not name:
            raise ValueError("entity name is required")
        object.__setattr__(self, "name", name)
        object.__setattr__(self, "kind", EntityKind(self.kind))
        object.__setattr__(self, "aliases", _normalize_aliases(self.aliases, name=name))
        metadata = dict(self.metadata)
        _reject_secret_keys(metadata)
        object.__setattr__(self, "metadata", metadata)
        object.__setattr__(self, "created_at", _normalize_datetime(self.created_at))
        object.__setattr__(self, "updated_at", _normalize_datetime(self.updated_at))

    def with_enabled(self, enabled: bool, *, updated_at: datetime | None = None) -> "TrackedEntity":
        return replace(
            self,
            enabled=enabled,
            updated_at=_normalize_datetime(updated_at or datetime.now(UTC)),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "entity_id": self.entity_id,
            "name": self.name,
            "kind": self.kind.value,
            "aliases": list(self.aliases),
            "enabled": self.enabled,
            "metadata": dict(self.metadata),
            "created_at": _format_datetime(self.created_at),
            "updated_at": _format_datetime(self.updated_at),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "TrackedEntity":
        return cls(
            entity_id=str(payload["entity_id"]),
            name=str(payload["name"]),
            kind=str(payload.get("kind") or EntityKind.COMPANY.value),
            aliases=[str(alias) for alias in payload.get("aliases") or []],
            enabled=bool(payload.get("enabled", True)),
            metadata=dict(payload.get("metadata") or {}),
            created_at=_parse_datetime(payload.get("created_at")),
            updated_at=_parse_datetime(payload.get("updated_at")),
        )


def _validate_id(value: str) -> str:
    entity_id = value.strip()
    if not entity_id:
        raise ValueError("entity_id is required")
    if not re.fullmatch(r"[A-Za-z0-9._:-]{1,128}", entity_id):
        raise ValueError("entity_id contains invalid characters")
    return entity_id


def _normalize_aliases(values: list[str], *, name: str) -> list[str]:
    seen = {name.casefold()}
    aliases = []
    for value in values:
        alias = str(value).strip()
        if not alias:
            continue
        normalized = alias.casefold()
        if normalized in seen:
            continue
        seen.add(normalized)
        aliases.append(alias)
    return aliases


def _reject_secret_keys(payload: dict[str, Any]) -> None:
    secret_fragments = ("api_key", "authorization", "bearer", "password", "secret", "token")
    for key in payload:
        normalized = str(key).lower()
        if any(fragment in normalized for fragment in secret_fragments):
            raise ValueError(f"entity metadata contains secret-like key: {key}")


def _normalize_datetime(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _format_datetime(value: datetime) -> str:
    return _normalize_datetime(value).isoformat().replace("+00:00", "Z")


def _parse_datetime(value: Any) -> datetime:
    if not value:
        return datetime.now(UTC)
    return datetime.fromisoformat(str(value).replace("Z", "+00:00")).astimezone(UTC)
