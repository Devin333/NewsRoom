from __future__ import annotations

import importlib
from pathlib import Path


def test_scoring_root_only_keeps_package_entrypoint() -> None:
    scoring_root = Path(__file__).resolve().parents[3] / "framework" / "scoring"
    root_files = sorted(path.name for path in scoring_root.iterdir() if path.is_file())

    assert root_files == ["__init__.py"]


def test_legacy_flat_imports_are_module_aliases() -> None:
    assert importlib.import_module("framework.scoring.models").ScoreBundle
    assert importlib.import_module("framework.scoring.scorer").WeightedScorer
    assert importlib.import_module("framework.scoring.ranker").PriorityRanker
    assert importlib.import_module("framework.scoring.recipe").ScoringRecipe
