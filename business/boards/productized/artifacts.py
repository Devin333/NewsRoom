from __future__ import annotations

from datetime import datetime, timezone as _tz
from typing import Any

from business.foundation import BoardType

UTC = _tz.utc


class ProductizedArtifactMetadataService:
    def __init__(self, *, board_type: BoardType | None = None) -> None:
        self.board_type = board_type

    def build(
        self,
        *,
        board_type: BoardType,
        request: dict[str, Any],
        cards: list[dict[str, Any]],
        quality_summary: dict[str, Any],
        subscription_payload: dict[str, Any],
    ) -> dict[str, Any]:
        return {
            "board_type": board_type.value,
            "run_id": str(request.get("run_id") or f"{board_type.value}-productized-run"),
            "topic": request.get("topic"),
            "generated_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            "schema_version": "business.board.productized.v1",
            "source_count": len(request.get("signals") or []),
            "card_count": len(cards),
            "quality_score": quality_summary.get("score") if isinstance(quality_summary, dict) else None,
            "subscription_ready": bool(subscription_payload.get("delivery_hints", {}).get("subscription_ready")),
            "improvement_ready": True,
        }

    def build_outputs(
        self,
        *,
        board_type: BoardType | None = None,
        request: dict[str, Any],
        cards: list[dict[str, Any]],
        quality_summary: dict[str, Any],
        subscription_payload: dict[str, Any],
    ) -> dict[str, Any]:
        resolved_board_type = board_type or self.board_type
        if resolved_board_type is None:
            raise ValueError("board_type is required for productized artifact metadata outputs")
        return {
            "artifact_metadata": self.build(
                board_type=resolved_board_type,
                request=request,
                cards=cards,
                quality_summary=quality_summary,
                subscription_payload=subscription_payload,
            )
        }


__all__ = ["ProductizedArtifactMetadataService"]
