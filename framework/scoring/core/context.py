from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any

from framework.shared.json import to_jsonable

if False:  # pragma: no cover
    from framework.scoring.recipes import ScoringRecipe


@dataclass(frozen=True)
class ScoringContext:
    run_id: str | None = None
    actor: str | None = None
    namespace: str | None = None
    tenant_id: str | None = None
    target_domain: str | None = None
    recipe_id: str | None = None
    policy_refs: list[str] = field(default_factory=list)
    memory_refs: list[str] = field(default_factory=list)
    trace_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "policy_refs", [str(ref) for ref in self.policy_refs])
        object.__setattr__(self, "memory_refs", [str(ref) for ref in self.memory_refs])
        object.__setattr__(self, "metadata", dict(self.metadata or {}))

    def child(self, **updates: Any) -> "ScoringContext":
        merged = dict(updates)
        if "metadata" in merged:
            merged["metadata"] = {**self.metadata, **dict(merged["metadata"] or {})}
        return replace(self, **merged)

    def with_recipe(self, recipe: "ScoringRecipe | str") -> "ScoringContext":
        recipe_id = getattr(recipe, "recipe_id", recipe)
        return self.child(recipe_id=str(recipe_id))

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "actor": self.actor,
            "namespace": self.namespace,
            "tenant_id": self.tenant_id,
            "target_domain": self.target_domain,
            "recipe_id": self.recipe_id,
            "policy_refs": list(self.policy_refs),
            "memory_refs": list(self.memory_refs),
            "trace_id": self.trace_id,
            "metadata": to_jsonable(self.metadata),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ScoringContext":
        return cls(
            run_id=str(payload["run_id"]) if payload.get("run_id") is not None else None,
            actor=str(payload["actor"]) if payload.get("actor") is not None else None,
            namespace=str(payload["namespace"]) if payload.get("namespace") is not None else None,
            tenant_id=str(payload["tenant_id"]) if payload.get("tenant_id") is not None else None,
            target_domain=(
                str(payload["target_domain"]) if payload.get("target_domain") is not None else None
            ),
            recipe_id=str(payload["recipe_id"]) if payload.get("recipe_id") is not None else None,
            policy_refs=[str(ref) for ref in payload.get("policy_refs") or []],
            memory_refs=[str(ref) for ref in payload.get("memory_refs") or []],
            trace_id=str(payload["trace_id"]) if payload.get("trace_id") is not None else None,
            metadata=dict(payload.get("metadata") or {}),
        )
