from __future__ import annotations

from typing import Any

from framework.workflow import FunctionStepRegistry
from business.boards.cross_board.workflows.daily_intelligence.evidence_step import build_evidence
from business.boards.cross_board.workflows.daily_intelligence.profiles import validate_daily_profile
from business.boards.cross_board.workflows.daily_intelligence.quality_gate_step import quality_gate
from business.boards.cross_board.workflows.daily_intelligence.source_processing import (
    deduplicate_sources,
    normalize_sources,
    rank_sources,
    require_sources,
)


def build_daily_intelligence_registry(
    *,
    profile: str,
    collect_sources: Any,
    draft_report: Any,
) -> FunctionStepRegistry:
    validate_daily_profile(profile)
    registry = FunctionStepRegistry()
    registry.register("daily.collect_sources", lambda buffer: collect_sources(buffer, profile))
    registry.register("daily.require_sources", require_sources)
    registry.register("daily.normalize_sources", normalize_sources)
    registry.register("daily.deduplicate_sources", deduplicate_sources)
    registry.register("daily.rank_sources", rank_sources)
    registry.register("daily.build_evidence", build_evidence)
    registry.register("daily.draft_report", lambda buffer: draft_report(buffer, profile))
    registry.register("daily.quality_gate", quality_gate)
    return registry
