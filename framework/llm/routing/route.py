from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from framework.llm.budget import LLMBudgetPolicy


@dataclass(frozen=True)
class ModelRoute:
    route_id: str
    primary_deployment_id: str
    fallback_deployment_ids: tuple[str, ...] = ()
    required_capabilities: tuple[str, ...] = ()
    budget_policy: LLMBudgetPolicy | None = None
    metadata: dict[str, Any] | None = None

    def deployment_chain(self) -> tuple[str, ...]:
        return (self.primary_deployment_id, *self.fallback_deployment_ids)

    def select_deployment(self) -> str:
        return self.primary_deployment_id

    def to_dict(self) -> dict[str, Any]:
        return {
            "route_id": self.route_id,
            "primary_deployment_id": self.primary_deployment_id,
            "fallback_deployment_ids": list(self.fallback_deployment_ids),
            "required_capabilities": list(self.required_capabilities),
            "budget_policy": self.budget_policy.__dict__ if self.budget_policy is not None else None,
            "metadata": dict(self.metadata or {}),
        }


@dataclass(frozen=True)
class LLMRoutingPolicy:
    default_route_id: str | None = None
    agent_routes: dict[str, str] = field(default_factory=dict)
    task_routes: dict[str, str] = field(default_factory=dict)
    agent_task_routes: dict[tuple[str, str], str] = field(default_factory=dict)

    def resolve(
        self,
        *,
        route_id: str | None = None,
        agent_id: str | None = None,
        task_type: str | None = None,
    ) -> str | None:
        resolved, _trace = self.resolve_with_trace(
            route_id=route_id,
            agent_id=agent_id,
            task_type=task_type,
        )
        return resolved

    def resolve_with_trace(
        self,
        *,
        route_id: str | None = None,
        agent_id: str | None = None,
        task_type: str | None = None,
    ) -> tuple[str | None, tuple[dict[str, Any], ...]]:
        trace: list[dict[str, Any]] = []
        explicit_route = _optional_text(route_id)
        if explicit_route:
            trace.append({"source": "explicit_route", "matched": True, "route_id": explicit_route})
            return explicit_route, tuple(trace)
        clean_agent_id = _optional_text(agent_id)
        clean_task_type = _optional_text(task_type)
        if clean_agent_id and clean_task_type:
            pair_route = self.agent_task_routes.get((clean_agent_id, clean_task_type))
            trace.append(
                {
                    "source": "agent_task_route",
                    "matched": pair_route is not None,
                    "agent_id": clean_agent_id,
                    "task_type": clean_task_type,
                    "route_id": pair_route,
                }
            )
            if pair_route:
                return pair_route, tuple(trace)
        if clean_agent_id:
            agent_route = self.agent_routes.get(clean_agent_id)
            trace.append(
                {
                    "source": "agent_route",
                    "matched": agent_route is not None,
                    "agent_id": clean_agent_id,
                    "route_id": agent_route,
                }
            )
            if agent_route:
                return agent_route, tuple(trace)
        if clean_task_type:
            task_route = self.task_routes.get(clean_task_type)
            trace.append(
                {
                    "source": "task_route",
                    "matched": task_route is not None,
                    "task_type": clean_task_type,
                    "route_id": task_route,
                }
            )
            if task_route:
                return task_route, tuple(trace)
        default_route = _optional_text(self.default_route_id)
        trace.append(
            {
                "source": "default_route",
                "matched": default_route is not None,
                "route_id": default_route,
            }
        )
        return default_route, tuple(trace)

    def to_dict(self) -> dict[str, Any]:
        return {
            "default_route_id": self.default_route_id,
            "agent_routes": dict(self.agent_routes),
            "task_routes": dict(self.task_routes),
            "agent_task_routes": [
                {"agent_id": agent_id, "task_type": task_type, "route_id": route_id}
                for (agent_id, task_type), route_id in self.agent_task_routes.items()
            ],
        }


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
