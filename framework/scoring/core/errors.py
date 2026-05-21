from __future__ import annotations


class ScoringError(Exception):
    """Base error for framework scoring failures."""


class ScoringRecipeError(ScoringError, ValueError):
    """Raised when a scoring recipe is invalid or cannot be loaded."""


class ScoringRegistryError(ScoringError, ValueError):
    """Raised when registry lookup or registration fails."""


class ScoringExecutionError(ScoringError, RuntimeError):
    """Raised when scoring runtime execution fails."""
