from __future__ import annotations

import re
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone as _tz
UTC = _tz.utc
from enum import Enum
from typing import Any


class SubscriptionCadence(str, Enum):
    DAILY = "daily"
    WEEKLY = "weekly"


class TopicSubscriptionNotFoundError(KeyError):
    def __init__(self, subscription_id: str) -> None:
        super().__init__(f"topic subscription not found: {subscription_id}")
        self.subscription_id = subscription_id


@dataclass(frozen=True)
class TopicSubscription:
    subscription_id: str
    topic: str
    cadence: SubscriptionCadence | str = SubscriptionCadence.WEEKLY
    profile: str = "live-offline"
    source_limit: int = 5
    enabled: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def __post_init__(self) -> None:
        object.__setattr__(self, "subscription_id", _validate_id(self.subscription_id))
        topic = self.topic.strip()
        if not topic:
            raise ValueError("topic is required")
        object.__setattr__(self, "topic", topic)
        object.__setattr__(self, "cadence", SubscriptionCadence(self.cadence))
        if self.profile not in {"live", "live-offline"}:
            raise ValueError("profile must be live or live-offline")
        if self.source_limit < 1:
            raise ValueError("source_limit must be greater than zero")
        metadata = dict(self.metadata)
        _reject_secret_keys(metadata)
        object.__setattr__(self, "metadata", metadata)
        object.__setattr__(self, "created_at", _normalize_datetime(self.created_at))
        object.__setattr__(self, "updated_at", _normalize_datetime(self.updated_at))

    def with_enabled(self, enabled: bool, *, updated_at: datetime | None = None) -> "TopicSubscription":
        return replace(
            self,
            enabled=enabled,
            updated_at=_normalize_datetime(updated_at or datetime.now(UTC)),
        )

    def to_dict(self) -> dict[str, Any]:
        cadence = SubscriptionCadence(self.cadence)
        return {
            "subscription_id": self.subscription_id,
            "topic": self.topic,
            "cadence": cadence.value,
            "profile": self.profile,
            "source_limit": self.source_limit,
            "enabled": self.enabled,
            "metadata": dict(self.metadata),
            "created_at": _format_datetime(self.created_at),
            "updated_at": _format_datetime(self.updated_at),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "TopicSubscription":
        return cls(
            subscription_id=str(payload["subscription_id"]),
            topic=str(payload["topic"]),
            cadence=str(payload.get("cadence") or SubscriptionCadence.WEEKLY.value),
            profile=str(payload.get("profile") or "live-offline"),
            source_limit=int(payload.get("source_limit") or 5),
            enabled=bool(payload.get("enabled", True)),
            metadata=dict(payload.get("metadata") or {}),
            created_at=_parse_datetime(payload.get("created_at")),
            updated_at=_parse_datetime(payload.get("updated_at")),
        )


def _validate_id(value: str) -> str:
    subscription_id = value.strip()
    if not subscription_id:
        raise ValueError("subscription_id is required")
    if not re.fullmatch(r"[A-Za-z0-9._:-]{1,128}", subscription_id):
        raise ValueError("subscription_id contains invalid characters")
    return subscription_id


def _reject_secret_keys(payload: dict[str, Any]) -> None:
    secret_fragments = ("api_key", "authorization", "bearer", "password", "secret", "token")
    for key in payload:
        normalized = str(key).lower()
        if any(fragment in normalized for fragment in secret_fragments):
            raise ValueError(f"subscription metadata contains secret-like key: {key}")


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
