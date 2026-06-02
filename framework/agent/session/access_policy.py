"""Access policy primitives for shared agent sessions."""

from __future__ import annotations

from dataclasses import dataclass

from framework.agent.session.models import AgentSessionItem, SessionVisibility
from framework.agent.session.roles import SESSION_RETENTION_ARCHIVE, SESSION_RETENTION_SUPERSEDE


@dataclass(frozen=True)
class SessionRoleSpec:
    """Read/write policy for one session role."""

    role: str
    readable_by: tuple[str, ...] = ("*",)
    writable_by: tuple[str, ...] = ("*",)
    private_readable_by: tuple[str, ...] = ()
    visibility: SessionVisibility = SessionVisibility.SHARED
    max_items: int | None = None
    overflow_action: str = SESSION_RETENTION_SUPERSEDE

    def __post_init__(self) -> None:
        object.__setattr__(self, "role", str(self.role))
        object.__setattr__(self, "readable_by", tuple(str(item) for item in self.readable_by))
        object.__setattr__(self, "writable_by", tuple(str(item) for item in self.writable_by))
        object.__setattr__(self, "private_readable_by", tuple(str(item) for item in self.private_readable_by))
        object.__setattr__(self, "visibility", SessionVisibility(str(self.visibility)))
        if self.max_items is not None:
            object.__setattr__(self, "max_items", max(1, int(self.max_items)))
        action = str(self.overflow_action or SESSION_RETENTION_SUPERSEDE)
        if action not in {SESSION_RETENTION_SUPERSEDE, SESSION_RETENTION_ARCHIVE}:
            raise ValueError("overflow_action must be either supersede or archive")
        object.__setattr__(self, "overflow_action", action)


class SessionAccessPolicy:
    """Role and visibility policy for shared agent sessions."""

    def __init__(
        self,
        role_specs: tuple[SessionRoleSpec, ...] | None = None,
        *,
        orchestrator_agent_ids: tuple[str, ...] = ("orchestrator", "paper-analysis-orchestrator"),
    ) -> None:
        self._role_specs = {spec.role: spec for spec in (role_specs or ())}
        self._orchestrator_agent_ids = tuple(orchestrator_agent_ids)

    def can_read(self, *, agent_id: str, item: AgentSessionItem) -> bool:
        """Return whether an agent may read an item."""

        spec = self._role_specs.get(item.role)
        if item.visibility == SessionVisibility.PRIVATE:
            return (
                item.agent_id == agent_id
                or self._is_orchestrator(agent_id)
                or (spec is not None and _matches(agent_id, spec.private_readable_by))
            )
        if spec is None:
            return item.visibility in {SessionVisibility.PUBLIC, SessionVisibility.SHARED, SessionVisibility.FINAL}
        return _matches(agent_id, spec.readable_by)

    def can_write(self, *, agent_id: str, role: str) -> bool:
        """Return whether an agent may write a role."""

        spec = self._role_specs.get(role)
        if spec is None:
            return True
        return _matches(agent_id, spec.writable_by)

    def visibility_for_role(self, role: str, fallback: SessionVisibility) -> SessionVisibility:
        """Return configured visibility for a role when one exists."""

        spec = self._role_specs.get(role)
        return spec.visibility if spec is not None else fallback

    def spec_for_role(self, role: str) -> SessionRoleSpec | None:
        """Return the configured role spec, if any."""

        return self._role_specs.get(role)

    def _is_orchestrator(self, agent_id: str) -> bool:
        return agent_id in self._orchestrator_agent_ids or agent_id.endswith("-orchestrator")


def _matches(agent_id: str, allowed: tuple[str, ...]) -> bool:
    return "*" in allowed or agent_id in allowed
