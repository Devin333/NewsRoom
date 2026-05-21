from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from framework.scoring.core.errors import ScoringRecipeError
from framework.scoring.recipes.models import ScoringRecipe


class RecipeLoader(Protocol):
    def load(self, recipe_id: str) -> ScoringRecipe:
        ...


@dataclass(frozen=True)
class InMemoryRecipeLoader:
    recipes: dict[str, ScoringRecipe] = field(default_factory=dict)

    def load(self, recipe_id: str) -> ScoringRecipe:
        key = str(recipe_id)
        if key not in self.recipes:
            available = ", ".join(sorted(self.recipes)) or "none"
            raise ScoringRecipeError(f"unknown recipe id '{key}'. Available recipes: {available}")
        recipe = self.recipes[key]
        return recipe if isinstance(recipe, ScoringRecipe) else ScoringRecipe.from_dict(dict(recipe))
