from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class PermissionChecker:
    permissions_by_actor: Mapping[str, Iterable[str]] = field(default_factory=dict)

    def can(self, actor: Any, action: str, resource: str) -> bool:
        permissions = _actor_permissions(actor, self.permissions_by_actor)
        requested = f"{action}:{resource}"
        return any(
            permission in permissions
            for permission in (
                "*",
                requested,
                f"{action}:*",
                f"*:{resource}",
            )
        )

    def require(self, actor: Any, action: str, resource: str) -> None:
        if not self.can(actor, action, resource):
            actor_name = _actor_name(actor)
            raise PermissionError(f"{actor_name} is not allowed to {action} {resource}")


def _actor_permissions(actor: Any, permissions_by_actor: Mapping[str, Iterable[str]]) -> set[str]:
    direct = getattr(actor, "permissions", None)
    if direct is not None:
        return {str(permission) for permission in direct}
    if isinstance(actor, Mapping) and "permissions" in actor:
        return {str(permission) for permission in actor["permissions"]}
    return {str(permission) for permission in permissions_by_actor.get(_actor_name(actor), ())}


def _actor_name(actor: Any) -> str:
    if isinstance(actor, str):
        return actor
    if isinstance(actor, Mapping):
        return str(actor.get("actor") or actor.get("id") or actor.get("name") or "anonymous")
    return str(getattr(actor, "actor", None) or getattr(actor, "id", None) or getattr(actor, "name", None) or actor)
