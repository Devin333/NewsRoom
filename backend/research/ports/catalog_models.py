"""Persistence-facing aliases for benchmark catalog models.

Adapters import this module instead of reaching into the benchmark package;
the application/domain contract remains replaceable at the port boundary.
"""

from backend.research.benchmark.models import ResearchSOTAClaim, ResearchScore

__all__ = ["ResearchSOTAClaim", "ResearchScore"]
