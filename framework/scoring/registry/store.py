from __future__ import annotations

from typing import Any

from framework.scoring.algorithms import Scorer, ScoringAlgorithm
from framework.scoring.calibration import ScoreCalibrator
from framework.scoring.core.errors import ScoringRegistryError
from framework.scoring.explanation import ExplanationBuilder
from framework.scoring.features import FeatureNormalizer
from framework.scoring.fusion import RankFusion
from framework.scoring.gates import GateSpec
from framework.scoring.ranking import Ranker


class ScoringRegistry:
    def __init__(self) -> None:
        self._algorithms: dict[str, ScoringAlgorithm] = {}
        self._rankers: dict[str, Ranker] = {}
        self._fusions: dict[str, RankFusion] = {}
        self._calibrators: dict[str, ScoreCalibrator] = {}
        self._explainers: dict[str, ExplanationBuilder] = {}
        self._normalizers: dict[str, FeatureNormalizer] = {}
        self._gate_specs: dict[str, GateSpec] = {}

    @property
    def _scorers(self) -> dict[str, Scorer]:
        return self._algorithms

    def register_algorithm(self, algorithm: ScoringAlgorithm) -> None:
        algorithm_id = str(getattr(algorithm, "algorithm_id", getattr(algorithm, "scorer_id", "")))
        if not algorithm_id:
            raise ScoringRegistryError("algorithm_id is required")
        self._algorithms[algorithm_id] = algorithm

    def register_scorer(self, scorer: Scorer) -> None:
        self.register_algorithm(scorer)

    def register_ranker(self, ranker: Ranker) -> None:
        self._rankers[str(ranker.ranker_id)] = ranker

    def register_fusion(self, fusion: RankFusion) -> None:
        self._fusions[str(fusion.fusion_id)] = fusion

    def register_calibrator(self, calibrator: ScoreCalibrator) -> None:
        self._calibrators[str(calibrator.calibrator_id)] = calibrator

    def register_explainer(self, explainer: ExplanationBuilder) -> None:
        self._explainers[str(explainer.explainer_id)] = explainer

    def register_normalizer(self, normalizer: FeatureNormalizer) -> None:
        self._normalizers[str(normalizer.normalizer_id)] = normalizer

    def register_gate_spec(self, gate_spec: GateSpec) -> None:
        self._gate_specs[str(gate_spec.gate_id)] = gate_spec

    def require_algorithm(self, algorithm_id: str) -> ScoringAlgorithm:
        return _require(self._algorithms, algorithm_id, "algorithm")

    def require_scorer(self, scorer_id: str) -> Scorer:
        try:
            return self.require_algorithm(scorer_id)
        except ScoringRegistryError as exc:
            available = ", ".join(sorted(self._algorithms)) or "none"
            raise ScoringRegistryError(f"unknown scorer id '{scorer_id}'. Available scorers: {available}") from exc

    def require_ranker(self, ranker_id: str) -> Ranker:
        return _require(self._rankers, ranker_id, "ranker")

    def require_fusion(self, fusion_id: str) -> RankFusion:
        return _require(self._fusions, fusion_id, "fusion")

    def require_calibrator(self, calibrator_id: str) -> ScoreCalibrator:
        return _require(self._calibrators, calibrator_id, "calibrator")

    def require_explainer(self, explainer_id: str) -> ExplanationBuilder:
        return _require(self._explainers, explainer_id, "explainer")

    def require_normalizer(self, normalizer_id: str) -> FeatureNormalizer:
        return _require(self._normalizers, normalizer_id, "normalizer")

    def require_gate_spec(self, gate_id: str) -> GateSpec:
        return _require(self._gate_specs, gate_id, "gate spec")

    def describe(self) -> dict[str, list[str]]:
        algorithms = sorted(self._algorithms)
        return {
            "algorithms": algorithms,
            "scorers": algorithms,
            "rankers": sorted(self._rankers),
            "fusions": sorted(self._fusions),
            "calibrators": sorted(self._calibrators),
            "explainers": sorted(self._explainers),
            "normalizers": sorted(self._normalizers),
            "gate_specs": sorted(self._gate_specs),
        }


def build_default_scoring_registry() -> ScoringRegistry:
    from framework.scoring.registry.defaults import register_default_plugins

    registry = ScoringRegistry()
    register_default_plugins(registry)
    return registry


def _require(registry: dict[str, Any], item_id: str, item_type: str):
    key = str(item_id)
    if key in registry:
        return registry[key]
    available = ", ".join(sorted(registry)) or "none"
    plural = item_type if item_type.endswith("s") else f"{item_type}s"
    raise ScoringRegistryError(f"unknown {item_type} id '{key}'. Available {plural}: {available}")
