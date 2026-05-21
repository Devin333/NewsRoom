from __future__ import annotations

import pytest

from framework.scoring import GateSpec, ScoringRegistryError, build_default_scoring_registry


def test_default_registry_describes_v2_extension_points() -> None:
    registry = build_default_scoring_registry()
    description = registry.describe()

    assert "weighted_linear" in description["algorithms"]
    assert "clamp" in description["normalizers"]
    assert "requires_evidence" in description["gate_specs"]
    assert registry.require_algorithm("weighted_linear").scorer_id == "weighted_linear"
    assert registry.require_normalizer("clamp").normalizer_id == "clamp"
    assert isinstance(registry.require_gate_spec("requires_evidence"), GateSpec)


def test_registry_unknown_algorithm_raises_scoring_registry_error() -> None:
    with pytest.raises(ScoringRegistryError, match="Available algorithms"):
        build_default_scoring_registry().require_algorithm("missing")
