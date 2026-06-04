from __future__ import annotations

from business.research.taxonomy import TaxonomyRegistry


def test_default_taxonomy_registry_contains_prd_levels() -> None:
    registry = TaxonomyRegistry.default()

    assert "Code" in registry.labels_for("domain")
    assert "Tool Use" in registry.labels_for("area")
    assert "paper reading" in registry.labels_for("task")
    assert registry.has_term("task", "paper_reading")
