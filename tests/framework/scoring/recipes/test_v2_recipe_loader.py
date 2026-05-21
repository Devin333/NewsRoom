from __future__ import annotations

import pytest

from framework.scoring import InMemoryRecipeLoader, ScoringRecipe, ScoringRecipeError


def test_in_memory_recipe_loader_returns_recipe_and_lists_missing() -> None:
    recipe = ScoringRecipe(recipe_id="recipe", version="1", target_type="thing", scorers=["weighted_linear"])
    loader = InMemoryRecipeLoader({"recipe": recipe})

    assert loader.load("recipe") == recipe
    with pytest.raises(ScoringRecipeError, match="Available recipes: recipe"):
        loader.load("missing")
