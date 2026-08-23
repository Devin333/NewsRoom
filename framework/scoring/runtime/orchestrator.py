from __future__ import annotations

from dataclasses import replace
from typing import Any

from framework.scoring.core import (
    ScoreBundle,
    ScoringContext,
    ScoringResult,
    ScoringStepTrace,
    ScoringTarget,
    ScoringTrace,
    clamp_score,
)
from framework.scoring.features import FeatureVector
from framework.scoring.gates import GateResult, GateRunner, GateSpec
from framework.scoring.ranking import PriorityRanker
from framework.scoring.recipes import RecipeValidator, ScoringRecipe
from framework.scoring.registry import ScoringRegistry, build_default_scoring_registry
from framework.shared.time import utc_now
from framework.shared.graph_identity import GraphExecutionIdentity


class ScoringRuntime:
    def __init__(
        self,
        *,
        registry: ScoringRegistry | None = None,
        gate_runner: GateRunner | None = None,
        validator: RecipeValidator | None = None,
    ) -> None:
        self.registry = registry or build_default_scoring_registry()
        self.gate_runner = gate_runner or GateRunner()
        self.validator = validator or RecipeValidator()

    def score_object(
        self,
        target: ScoringTarget,
        *,
        features: FeatureVector,
        recipe: ScoringRecipe,
        context: ScoringContext | None = None,
        execution_identity: GraphExecutionIdentity | None = None,
    ) -> ScoringResult:
        self._validate_recipe(recipe)
        actual_context = (context or ScoringContext()).with_recipe(recipe)
        trace = ScoringTrace.create(
            recipe_id=recipe.recipe_id,
            target_id=target.target_id,
            target_type=target.target_type,
            metadata={"trace_level": recipe.trace_level},
            execution_identity=execution_identity,
        )

        if recipe.normalizers:
            normalizer_step = _step("normalizers", "normalizer", input_summary={"normalizers": recipe.normalizers}, execution_identity=execution_identity)
            features = self._run_normalizers(features, recipe=recipe, context=actual_context)
            trace = trace.add_step(normalizer_step.finish(output_summary={"feature_count": len(features.values)}))

        gate_specs = self._resolve_gate_specs(recipe)
        gate_step = _step("gates", "gate", input_summary={"gate_count": len(gate_specs)}, execution_identity=execution_identity)
        gate_results = self.gate_runner.run(gate_specs, target=target, features=features, context=actual_context)
        trace = trace.add_step(gate_step.finish(output_summary={"gate_count": len(gate_results)}))

        scorer_step = _step("scorers", "scorer", input_summary={"scorers": recipe.scorer_ids()}, execution_identity=execution_identity)
        bundle = self._run_scorers(target=target, features=features, recipe=recipe, context=actual_context)
        trace = trace.add_step(scorer_step.finish(output_summary={"final_score": bundle.final_score}))

        gate_apply_step = _step("apply_gates", "gate_application", execution_identity=execution_identity)
        bundle, blocked, review_required, warnings = self._apply_gates(bundle, gate_results)
        trace = trace.add_step(
            gate_apply_step.finish(output_summary={"final_score": bundle.final_score, "blocked": blocked})
        )

        result = ScoringResult(
            target_id=target.target_id,
            target_type=target.target_type,
            recipe_id=recipe.recipe_id,
            score=bundle,
            gates=gate_results,
            warnings=warnings,
            blocked=blocked,
            review_required=review_required,
            metadata={
                **target.metadata,
                "trace_id": trace.trace_id,
                "target_tags": list(target.tags),
            },
        )

        calibrator_step = _step("calibrators", "calibrator", input_summary={"calibrators": recipe.calibrators}, execution_identity=execution_identity)
        result = self._run_calibrators(result, recipe=recipe, context=actual_context)
        trace = trace.add_step(calibrator_step.finish(output_summary={"final_score": result.final_score}))

        explanation_step = _step("explanation", "explainer", input_summary={"explainer": recipe.explainer or "template"}, execution_identity=execution_identity)
        explanation = self._build_explanation(
            target=target,
            features=features,
            recipe=recipe,
            result=result,
            context=actual_context,
        )
        trace = trace.add_step(explanation_step.finish(output_summary={"length": len(explanation)}))
        return replace(result, explanation=explanation, trace=trace)

    def rank_list(
        self,
        targets: list[ScoringTarget],
        *,
        feature_vectors: dict[str, FeatureVector],
        recipe: ScoringRecipe,
        context: ScoringContext | None = None,
        execution_identity: GraphExecutionIdentity | None = None,
    ):
        results: list[ScoringResult] = []
        warnings: list[str] = []
        for target in targets:
            features = feature_vectors.get(target.target_id)
            if features is None:
                warnings.append(f"missing feature vector for target {target.target_id}")
                continue
            results.append(
                self.score_object(
                    target,
                    features=features,
                    recipe=recipe,
                    context=context,
                    execution_identity=execution_identity,
                )
            )
        rankers = recipe.rankers or ["priority"]
        ranking = PriorityRanker().rank(results, recipe=recipe, context=context or ScoringContext())
        for ranker_id in rankers:
            ranker = self.registry.require_ranker(ranker_id)
            ranking = ranker.rank([item.result for item in ranking.items], recipe=recipe, context=context or ScoringContext())
        return replace(ranking, warnings=[*ranking.warnings, *warnings])

    def score_path(
        self,
        path_target: ScoringTarget,
        *,
        features: FeatureVector,
        recipe: ScoringRecipe,
        context: ScoringContext | None = None,
        execution_identity: GraphExecutionIdentity | None = None,
    ) -> ScoringResult:
        if not any("graph_path" in scorer_id or "path" in scorer_id for scorer_id in recipe.scorers):
            raise ValueError("score_path requires a graph path scorer in recipe.scorers")
        return self.score_object(
            path_target,
            features=features,
            recipe=recipe,
            context=context,
            execution_identity=execution_identity,
        )

    def fuse_rankings(
        self,
        rankings: list,
        *,
        recipe: ScoringRecipe,
        context: ScoringContext | None = None,
    ):
        fusion = self.registry.require_fusion(recipe.fusion or "rrf")
        return fusion.fuse(rankings, recipe=recipe, context=context or ScoringContext())

    def _run_normalizers(
        self,
        features: FeatureVector,
        *,
        recipe: ScoringRecipe,
        context: ScoringContext,
    ) -> FeatureVector:
        normalized = features
        for normalizer_id in recipe.normalizers:
            normalized = self.registry.require_normalizer(normalizer_id).normalize(normalized, context)
        return normalized

    def _run_scorers(
        self,
        *,
        target: ScoringTarget,
        features: FeatureVector,
        recipe: ScoringRecipe,
        context: ScoringContext,
    ) -> ScoreBundle:
        bundles = [
            self.registry.require_scorer(scorer_id).score(
                target=target,
                features=features,
                recipe=recipe,
                context=context,
            )
            for scorer_id in recipe.scorers
        ]
        return self._combine_bundles(bundles, recipe)

    def _apply_gates(
        self,
        bundle: ScoreBundle,
        gate_results: list[GateResult],
    ) -> tuple[ScoreBundle, bool, bool, list[str]]:
        score = bundle.final_score
        blocked = False
        review_required = False
        warnings: list[str] = []
        for gate in gate_results:
            if gate.blocked:
                blocked = True
                score = 0.0
            if gate.score_cap is not None:
                score = min(score, gate.score_cap)
            if gate.penalty:
                score = max(0.0, score - gate.penalty)
            if gate.boost:
                score = min(1.0, score + gate.boost)
            if gate.review_required:
                review_required = True
            if not gate.passed or gate.boost:
                warnings.append(gate.reason or gate.gate_id)
        score = clamp_score(score)
        return (
            replace(
                bundle.with_gated_score(score),
                metadata={**bundle.metadata, "gate_count": len(gate_results)},
            ),
            blocked,
            review_required,
            warnings,
        )

    def _combine_bundles(
        self,
        bundles: list[ScoreBundle],
        recipe: ScoringRecipe,
    ) -> ScoreBundle:
        if not bundles:
            return ScoreBundle.from_raw_score(0.0)
        configured_weights = dict(recipe.params.get("scorer_weights") or {})
        weighted_total = 0.0
        total_weight = 0.0
        factors = []
        channels: dict[str, list[float]] = {}
        confidence = 0.0
        risk = 0.0
        for bundle in bundles:
            scorer_id = str(bundle.metadata.get("scorer_id") or bundle.metadata.get("algorithm_id") or "")
            weight = max(0.0, float(configured_weights.get(scorer_id, 1.0)))
            weighted_total += bundle.final_score * weight
            total_weight += weight
            factors.extend(bundle.factors)
            confidence += bundle.confidence
            risk = max(risk, bundle.risk)
            for channel, value in bundle.channels.items():
                channels.setdefault(channel, []).append(value)
        score = clamp_score(weighted_total / total_weight) if total_weight > 0.0 else 0.0
        return ScoreBundle(
            raw_score=score,
            gated_score=score,
            calibrated_score=score,
            final_score=score,
            channels={channel: sum(values) / len(values) for channel, values in channels.items()},
            confidence=confidence / len(bundles),
            risk=risk,
            factors=factors,
            metadata={"scorer_ids": [bundle.metadata.get("scorer_id") for bundle in bundles]},
        )

    def _run_calibrators(
        self,
        result: ScoringResult,
        *,
        recipe: ScoringRecipe,
        context: ScoringContext,
    ) -> ScoringResult:
        calibrators = recipe.calibrators or ["noop"]
        calibrated = result
        for calibrator_id in calibrators:
            calibrated = self.registry.require_calibrator(calibrator_id).calibrate(
                calibrated,
                recipe=recipe,
                context=context,
            )
        return calibrated

    def _build_explanation(
        self,
        *,
        target: ScoringTarget,
        features: FeatureVector,
        recipe: ScoringRecipe,
        result: ScoringResult,
        context: ScoringContext,
    ) -> str:
        explainer = self.registry.require_explainer(recipe.explainer or "template")
        return explainer.explain(
            target=target,
            features=features,
            recipe=recipe,
            result=result,
            context=context,
        )

    def _resolve_gate_specs(self, recipe: ScoringRecipe) -> list[GateSpec]:
        raw_specs = recipe.params.get("gate_specs") or {}
        if isinstance(raw_specs, list):
            spec_by_id = {str(item.get("gate_id")): item for item in raw_specs if isinstance(item, dict)}
        else:
            spec_by_id = dict(raw_specs)
        specs: list[GateSpec] = []
        for gate_id in recipe.gates:
            raw = spec_by_id.get(gate_id)
            if raw is None:
                specs.append(self.registry.require_gate_spec(gate_id))
                continue
            if isinstance(raw, GateSpec):
                specs.append(raw)
            else:
                payload: dict[str, Any] = dict(raw)
                payload.setdefault("gate_id", gate_id)
                specs.append(GateSpec.from_dict(payload))
        return specs

    def _validate_recipe(self, recipe: ScoringRecipe) -> None:
        errors = self.validator.validate(recipe)
        if errors:
            raise ValueError("; ".join(errors))


def _step(step_id: str, step_type: str, *, input_summary: dict[str, Any] | None = None, execution_identity: GraphExecutionIdentity | None = None) -> ScoringStepTrace:
    return ScoringStepTrace(
        step_id=step_id,
        step_type=step_type,
        status="started",
        started_at=utc_now(),
        input_summary=dict(input_summary or {}),
        execution_identity=execution_identity,
    )
