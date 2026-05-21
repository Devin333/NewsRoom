from framework.scoring.adapters import features_from_dict, result_to_dict, target_from_dict
from framework.scoring.algorithms import (
    BayesianScorer,
    BayesianScoringAlgorithm,
    CompositeScoringAlgorithm,
    FreshnessDecayScorer,
    FreshnessDecayScoringAlgorithm,
    GatedWeightedScorer,
    GatedWeightedScoringAlgorithm,
    GraphPathScorer,
    GraphPathScoringAlgorithm,
    Scorer,
    ScoringAlgorithm,
    WeightedScorer,
    WeightedScoringAlgorithm,
    WilsonScorer,
    WilsonScoringAlgorithm,
)
from framework.scoring.calibration import FeedbackCalibrator, NoopCalibrator, PolicyCalibrator, ScoreCalibrator
from framework.scoring.core import (
    RankingItem,
    RankingResult,
    ScoreBundle,
    ScoreFactor,
    ScoreLevel,
    ScoreValue,
    ScoringContext,
    ScoringError,
    ScoringExecutionError,
    ScoringRecipeError,
    ScoringRegistryError,
    ScoringResult,
    ScoringStepTrace,
    ScoringTarget,
    ScoringTrace,
    TargetRef,
)
from framework.scoring.explanation import ExplanationBuilder, TemplateExplanationBuilder
from framework.scoring.features import (
    ClampFeatureNormalizer,
    FeatureNormalizer,
    FeatureProvider,
    FeatureValue,
    FeatureVector,
    MinMaxFeatureNormalizer,
    StaticFeatureProvider,
    feature_dict,
    merge_feature_vectors,
    missing_features,
)
from framework.scoring.fusion import BordaFusion, RankFusion, ReciprocalRankFusion, WeightedScoreFusion
from framework.scoring.gates import GateAction, GateResult, GateRunner, GateSpec, build_default_gate_specs
from framework.scoring.ranking import DedupRanker, DiversityRanker, PriorityRanker, Ranker
from framework.scoring.recipes import InMemoryRecipeLoader, RecipeLoader, RecipeStep, RecipeValidator, ScoringRecipe
from framework.scoring.registry import ScoringRegistry, build_default_scoring_registry, register_default_plugins
from framework.scoring.runtime import ScoringRuntime

import sys as _sys
from importlib import import_module as _import_module

_COMPAT_MODULE_ALIASES = {
    "context": "framework.scoring.core.context",
    "feature": "framework.scoring.features",
    "models": "framework.scoring.core.models",
    "ranker": "framework.scoring.ranking",
    "recipe": "framework.scoring.recipes",
    "scorer": "framework.scoring.algorithms",
    "target": "framework.scoring.core.target",
    "trace": "framework.scoring.core.trace",
}

for _legacy_name, _module_name in _COMPAT_MODULE_ALIASES.items():
    _module = _import_module(_module_name)
    _sys.modules[f"{__name__}.{_legacy_name}"] = _module
    globals()[_legacy_name] = _module

del _COMPAT_MODULE_ALIASES, _import_module, _legacy_name, _module, _module_name, _sys

__all__ = [
    "BayesianScorer",
    "BayesianScoringAlgorithm",
    "BordaFusion",
    "ClampFeatureNormalizer",
    "CompositeScoringAlgorithm",
    "DedupRanker",
    "DiversityRanker",
    "ExplanationBuilder",
    "FeatureNormalizer",
    "FeatureProvider",
    "FeatureValue",
    "FeatureVector",
    "FeedbackCalibrator",
    "FreshnessDecayScorer",
    "FreshnessDecayScoringAlgorithm",
    "GatedWeightedScorer",
    "GatedWeightedScoringAlgorithm",
    "GateAction",
    "GateResult",
    "GateRunner",
    "GateSpec",
    "GraphPathScorer",
    "GraphPathScoringAlgorithm",
    "InMemoryRecipeLoader",
    "MinMaxFeatureNormalizer",
    "NoopCalibrator",
    "PolicyCalibrator",
    "PriorityRanker",
    "RankFusion",
    "Ranker",
    "RankingItem",
    "RankingResult",
    "RecipeLoader",
    "RecipeStep",
    "RecipeValidator",
    "ReciprocalRankFusion",
    "ScoreBundle",
    "ScoreCalibrator",
    "ScoreFactor",
    "ScoreLevel",
    "ScoreValue",
    "Scorer",
    "ScoringAlgorithm",
    "ScoringContext",
    "ScoringError",
    "ScoringExecutionError",
    "ScoringRecipe",
    "ScoringRecipeError",
    "ScoringRegistry",
    "ScoringRegistryError",
    "ScoringResult",
    "ScoringRuntime",
    "ScoringStepTrace",
    "ScoringTarget",
    "ScoringTrace",
    "StaticFeatureProvider",
    "TargetRef",
    "TemplateExplanationBuilder",
    "WeightedScoreFusion",
    "WeightedScorer",
    "WeightedScoringAlgorithm",
    "WilsonScorer",
    "WilsonScoringAlgorithm",
    "build_default_gate_specs",
    "build_default_scoring_registry",
    "feature_dict",
    "features_from_dict",
    "merge_feature_vectors",
    "missing_features",
    "register_default_plugins",
    "result_to_dict",
    "target_from_dict",
]
