from __future__ import annotations

from framework.scoring.features.models import FeatureVector


def feature_dict(features: FeatureVector) -> dict[str, float]:
    return features.as_float_dict()


def merge_feature_vectors(*vectors: FeatureVector) -> FeatureVector:
    merged = FeatureVector()
    for vector in vectors:
        merged = merged.merge(vector)
    return merged


def missing_features(features: FeatureVector, required: list[str] | tuple[str, ...]) -> list[str]:
    present = set(features.values)
    return [str(name) for name in required if str(name) not in present]
