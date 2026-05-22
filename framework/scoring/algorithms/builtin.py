from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from framework.scoring.core.context import ScoringContext
from framework.scoring.core.models import ScoreBundle, ScoreFactor, clamp_score, normalize_weights
from framework.scoring.core.target import ScoringTarget
from framework.scoring.features import FeatureVector
from framework.scoring.recipes import ScoringRecipe


class ScoringAlgorithmProtocol(Protocol):
    @property
    def scorer_id(self) -> str: ...

    def score(
        self,
        *,
        target: ScoringTarget,
        features: FeatureVector,
        recipe: ScoringRecipe,
        context: ScoringContext,
    ) -> ScoreBundle: ...


@dataclass(frozen=True)
class WeightedScoringAlgorithm:
    algorithm_id: str = "weighted_linear"

    @property
    def scorer_id(self) -> str:
        return self.algorithm_id

    def score(
        self,
        *,
        target: ScoringTarget,
        features: FeatureVector,
        recipe: ScoringRecipe,
        context: ScoringContext,
    ) -> ScoreBundle:
        score, factors = _weighted_score(features.as_float_dict(), recipe.weights)
        channels = _channels(features, recipe)
        return ScoreBundle(
            raw_score=score,
            gated_score=score,
            calibrated_score=score,
            final_score=score,
            channels=channels,
            confidence=_feature_confidence(features),
            factors=factors,
            metadata={"scorer_id": self.scorer_id, "algorithm_id": self.algorithm_id},
        )


@dataclass(frozen=True)
class GatedWeightedScoringAlgorithm:
    algorithm_id: str = "gated_weighted"

    @property
    def scorer_id(self) -> str:
        return self.algorithm_id

    def score(
        self,
        *,
        target: ScoringTarget,
        features: FeatureVector,
        recipe: ScoringRecipe,
        context: ScoringContext,
    ) -> ScoreBundle:
        return WeightedScoringAlgorithm(algorithm_id=self.algorithm_id).score(
            target=target,
            features=features,
            recipe=recipe,
            context=context,
        )


@dataclass(frozen=True)
class WilsonScoringAlgorithm:
    algorithm_id: str = "wilson_score"
    positive_feature: str = "positive_count"
    total_feature: str = "total_count"
    z: float = 1.96

    @property
    def scorer_id(self) -> str:
        return self.algorithm_id

    def score(
        self,
        *,
        target: ScoringTarget,
        features: FeatureVector,
        recipe: ScoringRecipe,
        context: ScoringContext,
    ) -> ScoreBundle:
        positive_feature = str(recipe.params.get("positive_feature") or self.positive_feature)
        total_feature = str(recipe.params.get("total_feature") or self.total_feature)
        positive = max(0.0, features.get(positive_feature, 0.0))
        total = max(0.0, features.get(total_feature, 0.0))
        score = _wilson_score(positive, total, self.z)
        return ScoreBundle(
            raw_score=score,
            gated_score=score,
            calibrated_score=score,
            final_score=score,
            confidence=clamp_score(total / (total + 10.0)) if total > 0 else 0.0,
            factors=[
                ScoreFactor(name=positive_feature, value=score, weight=1.0, metadata={"raw_value": positive}),
                ScoreFactor(name=total_feature, value=clamp_score(total / 100.0), weight=0.0, metadata={"raw_value": total}),
            ],
            metadata={"scorer_id": self.scorer_id, "algorithm_id": self.algorithm_id, "positive": positive, "total": total},
        )


@dataclass(frozen=True)
class BayesianScoringAlgorithm:
    algorithm_id: str = "bayesian_smoothing"
    value_feature: str = "value"
    count_feature: str = "count"
    prior: float = 0.5
    prior_weight: float = 10.0

    @property
    def scorer_id(self) -> str:
        return self.algorithm_id

    def score(
        self,
        *,
        target: ScoringTarget,
        features: FeatureVector,
        recipe: ScoringRecipe,
        context: ScoringContext,
    ) -> ScoreBundle:
        value_feature = str(recipe.params.get("value_feature") or self.value_feature)
        count_feature = str(recipe.params.get("count_feature") or self.count_feature)
        prior = float(recipe.params.get("prior", self.prior))
        prior_weight = max(0.0, float(recipe.params.get("prior_weight", self.prior_weight)))
        value = clamp_score(features.get(value_feature, 0.0))
        count = max(0.0, features.get(count_feature, 0.0))
        denominator = count + prior_weight
        score = clamp_score(((value * count) + (prior * prior_weight)) / denominator) if denominator else value
        return ScoreBundle(
            raw_score=score,
            gated_score=score,
            calibrated_score=score,
            final_score=score,
            confidence=clamp_score(count / denominator) if denominator else 0.0,
            factors=[ScoreFactor(name=value_feature, value=value, weight=count, contribution=value * count)],
            metadata={"scorer_id": self.scorer_id, "algorithm_id": self.algorithm_id, "count": count, "prior": prior, "prior_weight": prior_weight},
        )


@dataclass(frozen=True)
class FreshnessDecayScoringAlgorithm:
    algorithm_id: str = "freshness_decay"
    age_days_feature: str = "age_days"
    half_life_days: float = 7.0

    @property
    def scorer_id(self) -> str:
        return self.algorithm_id

    def score(
        self,
        *,
        target: ScoringTarget,
        features: FeatureVector,
        recipe: ScoringRecipe,
        context: ScoringContext,
    ) -> ScoreBundle:
        age_feature = str(recipe.params.get("age_days_feature") or self.age_days_feature)
        half_life = max(0.0001, float(recipe.params.get("half_life_days", self.half_life_days)))
        age_days = max(0.0, features.get(age_feature, 0.0))
        score = clamp_score(0.5 ** (age_days / half_life))
        return ScoreBundle(
            raw_score=score,
            gated_score=score,
            calibrated_score=score,
            final_score=score,
            channels={"freshness": score},
            confidence=1.0,
            factors=[ScoreFactor(name=age_feature, value=score, weight=1.0, metadata={"age_days": age_days})],
            metadata={"scorer_id": self.scorer_id, "algorithm_id": self.algorithm_id, "half_life_days": half_life},
        )


@dataclass(frozen=True)
class GraphPathScoringAlgorithm:
    algorithm_id: str = "graph_path_score"

    @property
    def scorer_id(self) -> str:
        return self.algorithm_id

    def score(
        self,
        *,
        target: ScoringTarget,
        features: FeatureVector,
        recipe: ScoringRecipe,
        context: ScoringContext,
    ) -> ScoreBundle:
        score, factors = _weighted_score(features.as_float_dict(), recipe.weights)
        penalty = clamp_score(features.get("contradiction_penalty", 0.0))
        final = clamp_score(score - penalty)
        if "contradiction_penalty" in features.values:
            factors.append(ScoreFactor(name="contradiction_penalty", value=penalty, weight=1.0, contribution=-penalty))
        return ScoreBundle(
            raw_score=score,
            gated_score=final,
            calibrated_score=final,
            final_score=final,
            channels=_channels(features, recipe),
            confidence=features.get("evidence_chain_confidence", _feature_confidence(features)),
            risk=penalty,
            factors=factors,
            metadata={"scorer_id": self.scorer_id, "algorithm_id": self.algorithm_id},
        )


@dataclass(frozen=True)
class CompositeScoringAlgorithm:
    algorithm_id: str = "composite"
    algorithms: tuple[ScoringAlgorithmProtocol, ...] = ()
    weights: dict[str, float] | None = None

    @property
    def scorer_id(self) -> str:
        return self.algorithm_id

    def score(
        self,
        *,
        target: ScoringTarget,
        features: FeatureVector,
        recipe: ScoringRecipe,
        context: ScoringContext,
    ) -> ScoreBundle:
        bundles = [
            algorithm.score(target=target, features=features, recipe=recipe, context=context)
            for algorithm in self.algorithms
        ]
        if not bundles:
            return ScoreBundle.from_raw_score(0.0, metadata={"scorer_id": self.scorer_id, "algorithm_id": self.algorithm_id})
        weights = dict(self.weights or recipe.params.get("scorer_weights") or {})
        weighted_total = 0.0
        total_weight = 0.0
        factors: list[ScoreFactor] = []
        channels: dict[str, list[float]] = {}
        confidence = 0.0
        risk = 0.0
        for bundle in bundles:
            scorer_id = str(bundle.metadata.get("scorer_id") or bundle.metadata.get("algorithm_id") or "")
            weight = max(0.0, float(weights.get(scorer_id, 1.0)))
            weighted_total += bundle.final_score * weight
            total_weight += weight
            factors.extend(bundle.factors)
            confidence += bundle.confidence
            risk = max(risk, bundle.risk)
            for channel, value in bundle.channels.items():
                channels.setdefault(channel, []).append(value)
        score = clamp_score(weighted_total / total_weight) if total_weight > 0 else 0.0
        return ScoreBundle(
            raw_score=score,
            gated_score=score,
            calibrated_score=score,
            final_score=score,
            channels={channel: sum(values) / len(values) for channel, values in channels.items()},
            confidence=confidence / len(bundles),
            risk=risk,
            factors=factors,
            metadata={"scorer_id": self.scorer_id, "algorithm_id": self.algorithm_id},
        )


WeightedScorer = WeightedScoringAlgorithm
GatedWeightedScorer = GatedWeightedScoringAlgorithm
WilsonScorer = WilsonScoringAlgorithm
BayesianScorer = BayesianScoringAlgorithm
FreshnessDecayScorer = FreshnessDecayScoringAlgorithm
GraphPathScorer = GraphPathScoringAlgorithm


def _weighted_score(features: dict[str, float], weights: dict[str, float]) -> tuple[float, list[ScoreFactor]]:
    if not features:
        return 0.0, []
    weight_source = weights or {name: 1.0 for name in features}
    normalized = normalize_weights(weight_source)
    if not normalized or sum(normalized.values()) <= 0.0:
        return 0.0, []
    score = 0.0
    factors: list[ScoreFactor] = []
    for name, weight in normalized.items():
        value = clamp_score(features.get(name, 0.0))
        contribution = value * weight
        score += contribution
        factors.append(ScoreFactor(name=name, value=value, weight=weight, contribution=contribution))
    return clamp_score(score), factors


def _wilson_score(positive: float, total: float, z: float) -> float:
    if total <= 0:
        return 0.0
    p_hat = max(0.0, min(1.0, positive / total))
    z2 = z * z
    denominator = 1.0 + z2 / total
    centre = p_hat + z2 / (2.0 * total)
    margin = z * ((p_hat * (1.0 - p_hat) + z2 / (4.0 * total)) / total) ** 0.5
    return clamp_score((centre - margin) / denominator)


def _channels(features: FeatureVector, recipe: ScoringRecipe) -> dict[str, float]:
    channels: dict[str, float] = {}
    floats = features.as_float_dict()
    for channel, names in recipe.channels.items():
        values = [clamp_score(floats[name]) for name in names if name in floats]
        channels[channel] = sum(values) / len(values) if values else 0.0
    return channels


def _feature_confidence(features: FeatureVector) -> float:
    if not features.values:
        return 0.0
    return clamp_score(sum(feature.confidence for feature in features.values.values()) / len(features.values))
