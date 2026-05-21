from __future__ import annotations

from dataclasses import dataclass

from framework.scoring.core.context import ScoringContext
from framework.scoring.core.models import ScoreFactor, ScoringResult
from framework.scoring.core.target import ScoringTarget
from framework.scoring.features import FeatureVector
from framework.scoring.recipes import ScoringRecipe


@dataclass(frozen=True)
class TemplateExplanationBuilder:
    explainer_id: str = "template"
    template: str | None = None

    def explain(
        self,
        *,
        target: ScoringTarget,
        features: FeatureVector,
        recipe: ScoringRecipe,
        result: ScoringResult,
        context: ScoringContext,
    ) -> str:
        template = self.template or recipe.params.get("explanation_template") or (
            "{target_type} scored {score:.2f} by {recipe_id}. Top factors: {top_factors}. Gates: {gate_summary}."
        )
        return str(template).format(
            target_id=target.target_id,
            target_type=target.target_type,
            score=result.final_score,
            recipe_id=recipe.recipe_id,
            top_factors=", ".join(
                f"{factor.name}={factor.value:.2f}" for factor in self._top_factors(result)
            ) or "none",
            gate_summary=self._gate_summary(result),
        )

    def _top_factors(self, result: ScoringResult, limit: int = 3) -> list[ScoreFactor]:
        return sorted(
            result.score.factors,
            key=lambda factor: abs(float(factor.contribution or 0.0)),
            reverse=True,
        )[:limit]

    def _gate_summary(self, result: ScoringResult) -> str:
        if not result.gates:
            return "none"
        active: list[str] = []
        for gate in result.gates:
            payload = gate.to_dict() if hasattr(gate, "to_dict") else dict(gate)
            if payload.get("blocked") or payload.get("review_required") or payload.get("score_cap") is not None or payload.get("penalty") or payload.get("boost"):
                active.append(str(payload.get("gate_id")))
        return ", ".join(active) if active else "passed"
