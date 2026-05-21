from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from framework.shared.json import to_jsonable


@dataclass(frozen=True)
class RecipeStep:
    step_id: str
    step_type: str
    ref: str
    enabled: bool = True
    params: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not str(self.step_id).strip() or not str(self.step_type).strip() or not str(self.ref).strip():
            raise ValueError("recipe step id, type, and ref are required")
        object.__setattr__(self, "step_id", str(self.step_id))
        object.__setattr__(self, "step_type", str(self.step_type))
        object.__setattr__(self, "ref", str(self.ref))
        object.__setattr__(self, "params", dict(self.params or {}))

    def to_dict(self) -> dict[str, Any]:
        return {
            "step_id": self.step_id,
            "step_type": self.step_type,
            "ref": self.ref,
            "enabled": self.enabled,
            "params": to_jsonable(self.params),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "RecipeStep":
        return cls(
            step_id=str(payload["step_id"]),
            step_type=str(payload["step_type"]),
            ref=str(payload["ref"]),
            enabled=bool(payload.get("enabled", True)),
            params=dict(payload.get("params") or {}),
        )


@dataclass(frozen=True)
class ScoringRecipe:
    recipe_id: str
    version: str
    target_type: str
    feature_providers: list[str] = field(default_factory=list)
    normalizers: list[str] = field(default_factory=list)
    gates: list[str] = field(default_factory=list)
    scorers: list[str] = field(default_factory=list)
    rankers: list[str] = field(default_factory=list)
    fusion: str | None = None
    calibrators: list[str] = field(default_factory=list)
    explainer: str | None = None
    weights: dict[str, float] = field(default_factory=dict)
    channels: dict[str, list[str]] = field(default_factory=dict)
    params: dict[str, Any] = field(default_factory=dict)
    trace_level: str = "standard"
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "recipe_id", str(self.recipe_id).strip())
        object.__setattr__(self, "version", str(self.version).strip())
        object.__setattr__(self, "target_type", str(self.target_type).strip())
        for field_name in ("feature_providers", "normalizers", "gates", "scorers", "rankers", "calibrators"):
            object.__setattr__(self, field_name, [str(item) for item in getattr(self, field_name)])
        object.__setattr__(self, "weights", {str(k): float(v) for k, v in dict(self.weights or {}).items()})
        object.__setattr__(
            self,
            "channels",
            {str(k): [str(item) for item in v] for k, v in dict(self.channels or {}).items()},
        )
        object.__setattr__(self, "params", dict(self.params or {}))
        object.__setattr__(self, "metadata", dict(self.metadata or {}))

    def enabled_steps(self) -> list[RecipeStep]:
        steps: list[RecipeStep] = []
        steps.extend(RecipeStep(f"feature_provider:{ref}", "feature_provider", ref) for ref in self.feature_providers)
        steps.extend(RecipeStep(f"normalizer:{ref}", "normalizer", ref) for ref in self.normalizers)
        steps.extend(RecipeStep(f"gate:{ref}", "gate", ref) for ref in self.gates)
        steps.extend(RecipeStep(f"scorer:{ref}", "scorer", ref) for ref in self.scorers)
        steps.extend(RecipeStep(f"ranker:{ref}", "ranker", ref) for ref in self.rankers)
        if self.fusion:
            steps.append(RecipeStep(f"fusion:{self.fusion}", "fusion", self.fusion))
        steps.extend(RecipeStep(f"calibrator:{ref}", "calibrator", ref) for ref in self.calibrators)
        if self.explainer:
            steps.append(RecipeStep(f"explainer:{self.explainer}", "explainer", self.explainer))
        return steps

    def scorer_ids(self) -> list[str]:
        return list(self.scorers)

    def gate_ids(self) -> list[str]:
        return list(self.gates)

    def to_dict(self) -> dict[str, Any]:
        return {
            "recipe_id": self.recipe_id,
            "version": self.version,
            "target_type": self.target_type,
            "feature_providers": list(self.feature_providers),
            "normalizers": list(self.normalizers),
            "gates": list(self.gates),
            "scorers": list(self.scorers),
            "rankers": list(self.rankers),
            "fusion": self.fusion,
            "calibrators": list(self.calibrators),
            "explainer": self.explainer,
            "weights": dict(self.weights),
            "channels": {key: list(value) for key, value in self.channels.items()},
            "params": to_jsonable(self.params),
            "trace_level": self.trace_level,
            "metadata": to_jsonable(self.metadata),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ScoringRecipe":
        return cls(
            recipe_id=str(payload["recipe_id"]),
            version=str(payload["version"]),
            target_type=str(payload["target_type"]),
            feature_providers=[str(item) for item in payload.get("feature_providers") or []],
            normalizers=[str(item) for item in payload.get("normalizers") or []],
            gates=[str(item) for item in payload.get("gates") or []],
            scorers=[str(item) for item in payload.get("scorers") or []],
            rankers=[str(item) for item in payload.get("rankers") or []],
            fusion=str(payload["fusion"]) if payload.get("fusion") is not None else None,
            calibrators=[str(item) for item in payload.get("calibrators") or []],
            explainer=str(payload["explainer"]) if payload.get("explainer") is not None else None,
            weights={str(k): float(v) for k, v in dict(payload.get("weights") or {}).items()},
            channels={
                str(k): [str(item) for item in v]
                for k, v in dict(payload.get("channels") or {}).items()
            },
            params=dict(payload.get("params") or {}),
            trace_level=str(payload.get("trace_level") or "standard"),
            metadata=dict(payload.get("metadata") or {}),
        )


class RecipeValidator:
    def validate(self, recipe: ScoringRecipe) -> list[str]:
        errors: list[str] = []
        if not recipe.recipe_id:
            errors.append("recipe_id is required")
        if not recipe.version:
            errors.append("version is required")
        if not recipe.target_type:
            errors.append("target_type is required")
        if not recipe.scorers and not recipe.fusion:
            errors.append("recipe requires at least one scorer or a fusion")
        negative_weights = sorted(name for name, weight in recipe.weights.items() if weight < 0.0)
        if negative_weights:
            errors.append(f"weights must be non-negative: {', '.join(negative_weights)}")
        if recipe.trace_level not in {"minimal", "standard", "verbose"}:
            errors.append("trace_level must be one of: minimal, standard, verbose")
        return errors
