from __future__ import annotations

import pytest

from framework.scoring import build_default_scoring_registry


def test_default_registry_describes_builtin_plugins() -> None:
    registry = build_default_scoring_registry()
    description = registry.describe()

    assert "weighted_linear" in description["scorers"]
    assert "priority" in description["rankers"]
    assert "rrf" in description["fusions"]
    assert "noop" in description["calibrators"]
    assert "template" in description["explainers"]


def test_require_unknown_id_lists_available_ids() -> None:
    registry = build_default_scoring_registry()

    with pytest.raises(ValueError, match="Available scorers"):
        registry.require_scorer("missing")
