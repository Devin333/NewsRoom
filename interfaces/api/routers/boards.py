from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, Field

from interfaces.api.deps import ApiRouteHelpers, ApiServices


class BoardOutputRequest(BaseModel):
    items: list[dict[str, Any]] = Field(default_factory=list)
    topic: str | None = None


def create_router(services: ApiServices, helpers: ApiRouteHelpers) -> APIRouter:
    router = APIRouter()

    @router.get("/api/v1/boards")
    def list_boards():
        return helpers.success(
            {
                "boards": services.board_service_factory().list_boards(),
            }
        )

    @router.post("/api/v1/boards/{board_type}/output")
    def build_board_output(board_type: str, request: BoardOutputRequest):
        try:
            output = services.board_service_factory().build_board_output(
                board_type,
                request.items,
                topic=request.topic,
            )
        except ValueError as exc:
            return helpers.error(status_code=400, code="invalid_board_request", message=str(exc))
        return helpers.success(output.to_dict())

    return router
