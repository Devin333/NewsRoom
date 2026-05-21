from __future__ import annotations

from framework.scoring import (
    ClampFeatureNormalizer,
    FeatureVector,
    ScoringContext,
    ScoringTarget,
    StaticFeatureProvider,
    feature_dict,
    merge_feature_vectors,
    missing_features,
)


def test_static_provider_and_feature_utils() -> None:
    target = ScoringTarget(target_id="a", target_type="thing")
    vector = FeatureVector.from_scores({"raw": 2.0})
    provider = StaticFeatureProvider(features_by_target_id={"a": vector})

    provided = provider.build(target, ScoringContext())
    normalized = ClampFeatureNormalizer().normalize(provided, ScoringContext())
    merged = merge_feature_vectors(normalized, FeatureVector.from_scores({"other": 0.4}))

    assert normalized.get("raw") == 1.0
    assert feature_dict(merged) == {"raw": 1.0, "other": 0.4}
    assert missing_features(merged, ["raw", "missing"]) == ["missing"]
