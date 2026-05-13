from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Literal

from pydantic import BaseModel, Field


ActorType = Literal["user", "service", "mcp_client", "system", "anonymous"]

ROLE_PERMISSIONS: dict[str, set[str]] = {
    "admin": {
        "runs:create",
        "runs:read",
        "runs:cancel",
        "reports:read",
        "reports:publish",
        "sources:read",
        "sources:write",
        "memory:search",
        "workers:read",
        "schedules:write",
        "approvals:decide",
        "admin:diagnose",
    },
    "operator": {
        "runs:create",
        "runs:read",
        "runs:cancel",
        "reports:read",
        "sources:read",
        "memory:search",
        "workers:read",
        "schedules:write",
        "approvals:decide",
        "admin:diagnose",
    },
    "developer": {
        "runs:create",
        "runs:read",
        "reports:read",
        "sources:read",
        "memory:search",
        "workers:read",
        "admin:diagnose",
    },
    "reviewer": {
        "runs:read",
        "reports:read",
        "approvals:decide",
    },
    "analyst_readonly": {
        "runs:read",
        "reports:read",
        "sources:read",
        "memory:search",
        "workers:read",
    },
    "service": {
        "runs:create",
        "runs:read",
        "reports:read",
        "reports:publish",
        "sources:read",
        "sources:write",
        "memory:search",
        "workers:read",
        "schedules:write",
        "approvals:decide",
        "admin:diagnose",
    },
}


class ActorContext(BaseModel):
    actor_id: str
    actor_type: ActorType
    roles: list[str] = Field(default_factory=list)
    permissions: list[str] = Field(default_factory=list)
    request_id: str
    ip_address: str | None = None
    user_agent: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    def has_permission(self, permission: str) -> bool:
        return permission in self.effective_permissions

    @property
    def effective_permissions(self) -> set[str]:
        permissions = set(self.permissions)
        for role in self.roles:
            permissions.update(ROLE_PERMISSIONS.get(role, set()))
        return permissions


def actor_context_from_headers(
    headers: Mapping[str, str],
    *,
    request_id: str,
    ip_address: str | None = None,
) -> ActorContext:
    actor_id = _header(headers, "x-news-actor") or _header(headers, "x-api-client-id")
    actor_type = _header(headers, "x-news-actor-type") or "anonymous"
    roles = _csv_header(headers, "x-news-roles")
    permissions = _csv_header(headers, "x-news-permissions")
    if not actor_id and _header(headers, "authorization"):
        actor_id = "api-token"
        actor_type = "service"
        if not roles:
            roles = ["service"]
    if not actor_id:
        actor_id = "anonymous"
    return ActorContext(
        actor_id=actor_id,
        actor_type=_actor_type(actor_type),
        roles=roles,
        permissions=permissions,
        request_id=request_id,
        ip_address=ip_address,
        user_agent=_header(headers, "user-agent"),
    )


def _header(headers: Mapping[str, str], name: str) -> str | None:
    for key, value in headers.items():
        if key.lower() == name:
            text = str(value).strip()
            return text or None
    return None


def _csv_header(headers: Mapping[str, str], name: str) -> list[str]:
    value = _header(headers, name)
    if not value:
        return []
    return [item.strip() for item in value.split(",") if item.strip()]


def _actor_type(value: str) -> ActorType:
    normalized = value.strip().lower()
    if normalized in {"user", "service", "mcp_client", "system", "anonymous"}:
        return normalized  # type: ignore[return-value]
    return "anonymous"
