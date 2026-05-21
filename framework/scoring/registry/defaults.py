from __future__ import annotations

from framework.scoring.algorithms import (
    BayesianScoringAlgorithm,
    FreshnessDecayScoringAlgorithm,
    GatedWeightedScoringAlgorithm,
    GraphPathScoringAlgorithm,
    WeightedScoringAlgorithm,
    WilsonScoringAlgorithm,
)
from framework.scoring.calibration import FeedbackCalibrator, NoopCalibrator, PolicyCalibrator
from framework.scoring.explanation import TemplateExplanationBuilder
from framework.scoring.features import ClampFeatureNormalizer, MinMaxFeatureNormalizer
from framework.scoring.fusion import BordaFusion, ReciprocalRankFusion, WeightedScoreFusion
from framework.scoring.gates import build_default_gate_specs
from framework.scoring.ranking import DedupRanker, DiversityRanker, PriorityRanker


def register_default_plugins(registry) -> None:
    registry.register_algorithm(WeightedScoringAlgorithm())
    registry.register_algorithm(GatedWeightedScoringAlgorithm())
    registry.register_algorithm(WilsonScoringAlgorithm())
    registry.register_algorithm(BayesianScoringAlgorithm())
    registry.register_algorithm(FreshnessDecayScoringAlgorithm())
    registry.register_algorithm(GraphPathScoringAlgorithm())
    registry.register_ranker(PriorityRanker())
    registry.register_ranker(DiversityRanker())
    registry.register_ranker(DedupRanker())
    registry.register_fusion(ReciprocalRankFusion())
    registry.register_fusion(BordaFusion())
    registry.register_fusion(WeightedScoreFusion())
    registry.register_calibrator(NoopCalibrator())
    registry.register_calibrator(PolicyCalibrator())
    registry.register_calibrator(FeedbackCalibrator())
    registry.register_explainer(TemplateExplanationBuilder())
    registry.register_normalizer(ClampFeatureNormalizer())
    registry.register_normalizer(MinMaxFeatureNormalizer())
    for gate_spec in build_default_gate_specs().values():
        registry.register_gate_spec(gate_spec)
