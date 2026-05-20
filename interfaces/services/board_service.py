from __future__ import annotations

from dataclasses import asdict, is_dataclass
from typing import Any, cast

from pydantic import Field

from business.boards import (
    AINewsBoardService,
    CommunityPulseBoardService,
    CrossBoardService,
    PaperRadarBoardService,
    ProjectRadarBoardService,
)
from business.foundation import AnalysisContext, BoardType, PrimitiveModel, Report, Signal
from business.layers.output import BoardOutput


class BoardBuildResult(PrimitiveModel):
    board_type: BoardType
    output: BoardOutput


class CrossBoardBuildResult(PrimitiveModel):
    output: BoardOutput
    board_outputs: dict[str, BoardOutput] = Field(default_factory=dict)


class BoardApplicationService:
    def __init__(self) -> None:
        self._services = {
            BoardType.AI_NEWS: AINewsBoardService(),
            BoardType.PROJECT_RADAR: ProjectRadarBoardService(),
            BoardType.PAPER_RADAR: PaperRadarBoardService(),
            BoardType.COMMUNITY_PULSE: CommunityPulseBoardService(),
            BoardType.CROSS_BOARD: CrossBoardService(),
        }

    def list_boards(self) -> list[dict[str, Any]]:
        return [
            service.board_definition.to_dict()
            for service in self._services.values()
        ]

    def build_board_output(
        self,
        board_type: str | BoardType,
        items: list[Any],
        *,
        topic: str | None = None,
        context: AnalysisContext | None = None,
    ) -> BoardOutput:
        resolved_board_type = _board_type(board_type)
        resolved_context = _context_for_board(
            resolved_board_type,
            context=context,
            topic=topic,
        )
        return self._services[resolved_board_type].build_board_output(
            list(items),
            context=resolved_context,
        )

    def build_all_board_outputs(
        self,
        items: list[Any],
        *,
        topic: str | None = None,
        context: AnalysisContext | None = None,
    ) -> dict[str, BoardOutput]:
        outputs: dict[str, BoardOutput] = {}
        for board_type in (
            BoardType.AI_NEWS,
            BoardType.PROJECT_RADAR,
            BoardType.PAPER_RADAR,
            BoardType.COMMUNITY_PULSE,
        ):
            outputs[board_type.value] = self.build_board_output(
                board_type,
                items,
                topic=topic,
                context=context,
            )
        return outputs

    def build_cross_board_output(
        self,
        items: list[Any],
        *,
        topic: str | None = None,
        context: AnalysisContext | None = None,
    ) -> CrossBoardBuildResult:
        board_outputs = self.build_all_board_outputs(items, topic=topic, context=context)
        cross_board = self.build_board_output(
            BoardType.CROSS_BOARD,
            items,
            topic=topic,
            context=context,
        )
        return CrossBoardBuildResult(output=cross_board, board_outputs=board_outputs)

    def build_daily_digest(
        self,
        items: list[Any],
        *,
        topic: str | None = None,
        context: AnalysisContext | None = None,
    ) -> Report:
        output = self.build_board_output(
            BoardType.CROSS_BOARD,
            items,
            topic=topic,
            context=context,
        )
        report_payload = output.metadata.get("report")
        if not isinstance(report_payload, dict):
            raise ValueError("cross board output does not include a report payload")
        return Report.model_validate(report_payload)

    def attach_run_board_outputs(
        self,
        output: dict[str, Any],
        *,
        topic: str | None = None,
    ) -> None:
        items = _items_from_run_output(output)
        if not items:
            return
        cross_board_result = self.build_cross_board_output(items, topic=topic)
        output["board_outputs"] = {
            board_type: board_output.to_dict()
            for board_type, board_output in cross_board_result.board_outputs.items()
        }
        output["cross_board_output"] = cross_board_result.output.to_dict()


def _board_type(value: str | BoardType) -> BoardType:
    if isinstance(value, BoardType):
        return value
    normalized = str(value).strip().lower().replace("-", "_")
    if not normalized:
        raise ValueError("board_type is required")
    try:
        return BoardType(normalized)
    except ValueError as exc:
        valid = ", ".join(board_type.value for board_type in BoardType)
        raise ValueError(f"unsupported board_type: {value}; expected one of: {valid}") from exc


def _context_for_board(
    board_type: BoardType,
    *,
    context: AnalysisContext | None,
    topic: str | None,
) -> AnalysisContext:
    metadata = dict(context.metadata if context is not None else {})
    if topic:
        metadata["topic"] = topic
    if context is None:
        return AnalysisContext(board_type=board_type, metadata=metadata)
    return context.for_board(board_type).model_copy(update={"metadata": metadata})


def _items_from_run_output(output: dict[str, Any]) -> list[Any]:
    for key in ("signals", "ranked_items", "normalized_items", "raw_items"):
        value = output.get(key)
        if isinstance(value, list):
            if key == "ranked_items":
                return [_ranked_item_payload(item) for item in value]
            if key == "normalized_items":
                return [_normalized_item_payload(item) for item in value]
            return value
    evidence_bundle = output.get("evidence_bundle")
    evidence_items = _field_value(evidence_bundle, "items", default=None)
    if isinstance(evidence_items, list):
        return [_item_from_evidence(item) for item in evidence_items]
    return []


def _item_from_evidence(item: Any) -> dict[str, Any]:
    if isinstance(item, Signal):
        return item.to_dict()
    if hasattr(item, "to_dict"):
        payload = item.to_dict()
    elif isinstance(item, dict):
        payload = dict(item)
    else:
        payload = {}
    return {
        "source_item_id": str(payload.get("source_item_id") or payload.get("evidence_id") or payload.get("id") or payload.get("title") or "evidence"),
        "source_id": str(payload.get("source_id") or payload.get("source_name") or "evidence"),
        "source_name": str(payload.get("source_name") or payload.get("source_id") or "Evidence"),
        "source_type": str(payload.get("source_type") or "manual"),
        "title": str(payload.get("title") or payload.get("headline") or payload.get("summary") or "Evidence item"),
        "url": str(payload.get("source_url") or payload.get("url") or "manual://evidence"),
        "fetched_at": payload.get("fetched_at") or payload.get("collected_at"),
        "published_at": payload.get("published_at"),
        "summary": payload.get("summary") or payload.get("text"),
        "raw_content": payload.get("raw_content") or payload.get("content"),
        "authors": payload.get("authors") or [],
        "tags": payload.get("tags") or [],
        "language": payload.get("language"),
        "metadata": {
            key: value
            for key, value in payload.items()
            if key
            not in {
                "source_item_id",
                "source_id",
                "source_name",
                "source_type",
                "title",
                "url",
                "source_url",
                "fetched_at",
                "collected_at",
                "published_at",
                "summary",
                "text",
                "raw_content",
                "content",
                "authors",
                "tags",
                "language",
            }
        },
    }


def _ranked_item_payload(item: Any) -> Any:
    if is_dataclass(item):
        payload = asdict(cast(Any, item))
    elif hasattr(item, "to_dict"):
        payload = item.to_dict()
    elif isinstance(item, dict):
        payload = dict(item)
    else:
        payload = {}
    if isinstance(payload.get("item"), dict):
        return payload["item"]
    return payload


def _normalized_item_payload(item: Any) -> Any:
    if is_dataclass(item):
        payload = asdict(cast(Any, item))
    elif hasattr(item, "to_dict"):
        payload = item.to_dict()
    elif isinstance(item, dict):
        payload = dict(item)
    else:
        payload = {}
    return payload


def _field_value(value: Any, name: str, *, default: Any = None) -> Any:
    if isinstance(value, dict):
        return value.get(name, default)
    return getattr(value, name, default)
