from __future__ import annotations

from typing import Any

from business.boards._service import BoardServiceBase
from business.boards.productized.models import ProductizedBoardOutputBundle, ProductizedRunState
from business.boards.productized.payloads import card_report_item, summary_markdown
from business.foundation import AnalysisContext
from business.foundation.skills import BusinessSkillRuntime


class ProductizedBoardOutputService:
    def __init__(
        self,
        *,
        board_service: BoardServiceBase,
        skill_runtime: BusinessSkillRuntime,
        report_writing_service: "ProductizedReportWritingService" | None = None,
        bundle_builder: "ProductizedBoardOutputBundleBuilder" | None = None,
    ) -> None:
        self.board_service = board_service
        self.report_writing_service = report_writing_service or ProductizedReportWritingService(
            skill_runtime=skill_runtime,
        )
        self.bundle_builder = bundle_builder or ProductizedBoardOutputBundleBuilder()

    def build(
        self,
        *,
        request: dict[str, Any],
        context: AnalysisContext,
        ranked_signals: list[Any],
        productized_run: ProductizedRunState,
    ) -> ProductizedBoardOutputBundle:
        result = self.board_service.build_board_run_result(ranked_signals, context=context)
        report_result = self.report_writing_service.write(
            request=request,
            board_name=self.board_service.board_definition.name,
            cards=result.cards,
            productized_run=productized_run,
        )
        return self.bundle_builder.build(
            result=result,
            report_result=report_result,
            productized_run=productized_run,
        )


class ProductizedReportWritingService:
    def __init__(self, *, skill_runtime: BusinessSkillRuntime) -> None:
        self.skill_runtime = skill_runtime

    def write(
        self,
        *,
        request: dict[str, Any],
        board_name: str,
        cards: list[Any],
        productized_run: ProductizedRunState,
    ) -> Any:
        return self.skill_runtime.run_report_writing(
            {
                "title": f"{board_name} Summary",
                "audience": "subscriber",
                "style": "concise",
            },
            [card_report_item(card) for card in cards],
            trend_analyses=list(productized_run.trend_analysis.get("event_analyses", [])),
            run_id=productized_run.run_id,
            fail_on_skill_error=bool(request.get("fail_on_skill_error", False)),
        )


class ProductizedBoardOutputBundleBuilder:
    def build(
        self,
        *,
        result: Any,
        report_result: Any,
        productized_run: ProductizedRunState,
    ) -> ProductizedBoardOutputBundle:
        skill_traces = [*productized_run.skill_traces, report_result.to_dict()]
        run_state = productized_run.with_updates(skill_traces=skill_traces)
        result = result.model_copy(
            update={"metadata": {**dict(result.metadata), **run_state.runtime_metadata()}}
        )
        return ProductizedBoardOutputBundle(
            board_run_result=result,
            board_output=board_output_payload(result, run_state),
            cards=[card.to_dict() for card in result.cards],
            detail_pages=[page.to_dict() for page in result.detail_pages],
            insights=[insight.to_dict() for insight in result.insights],
            summary_md=report_result.output.get("markdown_report", summary_markdown(result)),
            skill_traces=skill_traces,
            run_state=run_state,
        )


def board_output_payload(result: Any, run_state: ProductizedRunState) -> dict[str, Any]:
    metadata = getattr(result, "metadata", {}) or {}
    board_output = dict(getattr(result, "board_output", {}) or metadata.get("board_output") or {})
    output_metadata = dict(board_output.get("metadata") or {})
    board_output["metadata"] = {**output_metadata, **run_state.board_output_metadata()}
    return board_output


__all__ = [
    "ProductizedBoardOutputBundleBuilder",
    "ProductizedBoardOutputService",
    "ProductizedReportWritingService",
    "board_output_payload",
]
