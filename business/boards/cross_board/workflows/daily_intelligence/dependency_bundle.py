from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from business.foundation.registry.source_registry import SourceRegistry
from business.layers.signal.source_health import BasicSourceHealthManager
from business.memory.intelligence_recall import IntelligenceMemoryRecallService
from framework.llm import LLMClient

from business.boards.cross_board.workflows.daily_intelligence.report_writer import ReportWriter
from business.boards.cross_board.workflows.daily_intelligence.source_collection import DailySourceCollector
from business.boards.cross_board.workflows.daily_intelligence.source_dispatcher import SourceDispatcher


@dataclass(frozen=True)
class DailyIntelligenceRuntime:
    artifact_root: Path
    source_registry: SourceRegistry
    source_dispatcher: SourceDispatcher
    source_collector: DailySourceCollector
    report_writer: ReportWriter
    source_health_manager: BasicSourceHealthManager
    recall_service: IntelligenceMemoryRecallService | None = None
    llm_client: LLMClient | None = None


__all__ = ["DailyIntelligenceRuntime"]
