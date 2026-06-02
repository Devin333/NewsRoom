from __future__ import annotations

from typing import Any

from business.foundation import AnalysisContext, BoardType, RunContext


def analysis_context_from_request(board_type: BoardType, request: dict[str, Any], run_id: str) -> AnalysisContext:
    return AnalysisContext(
        run_context=RunContext(run_id=run_id, run_type="board_productized", profile="productized"),
        board_type=board_type,
        metadata={"topic": request.get("topic"), "productized": True},
        enable_llm=False,
    )


def run_id_from_request(request: dict[str, Any], board_type: BoardType) -> str:
    return str(request.get("run_id") or f"{board_type.value}-productized-run")


__all__ = ["analysis_context_from_request", "run_id_from_request"]
