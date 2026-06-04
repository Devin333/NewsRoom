from __future__ import annotations

from fastapi import APIRouter

from framework.workers.scheduler import ScheduleNotFoundError
from interfaces.api.deps import ApiRouteHelpers, ApiServices
from interfaces.models import (
    ManualScheduleTriggerRequest,
    ScheduleUpsertRequest,
    ScheduleTickRequest,
)


def create_router(services: ApiServices, helpers: ApiRouteHelpers) -> APIRouter:
    router = APIRouter()

    @router.get("/api/v1/schedules")
    def list_schedules(include_disabled: bool = False):
        result = services.schedule_service_factory().list_schedules(enabled_only=not include_disabled)
        return helpers.success(result.to_dict())

    @router.post("/api/v1/schedules")
    def upsert_schedule(request: ScheduleUpsertRequest):
        try:
            result = services.schedule_service_factory().upsert_task_schedule(
                schedule_id=request.schedule_id,
                name=request.name,
                trigger_type=request.trigger_type,
                interval_seconds=(
                    request.interval_seconds if request.trigger_type == "interval" else None
                ),
                run_at=request.run_at if request.trigger_type == "interval" else None,
                task_type=request.task_type,
                payload_template=request.payload_template,
                queue_name=request.queue_name,
                enabled=request.enabled,
                metadata=request.metadata,
            )
        except ValueError as exc:
            return helpers.error(status_code=400, code="invalid_schedule", message=str(exc))
        return helpers.success(result.to_dict())

    @router.post("/api/v1/schedules/tick")
    def tick_schedules(request: ScheduleTickRequest | None = None):
        actual_request = request or ScheduleTickRequest()
        result = services.schedule_service_factory().tick(
            now=actual_request.now,
            enabled_only=not actual_request.include_disabled,
        )
        return helpers.success(result.to_dict())

    @router.post("/api/v1/schedules/{schedule_id}/trigger")
    def trigger_schedule(schedule_id: str, request: ManualScheduleTriggerRequest | None = None):
        actual_request = request or ManualScheduleTriggerRequest()
        try:
            result = services.schedule_service_factory().trigger_manual(
                schedule_id,
                now=actual_request.now,
            )
        except ScheduleNotFoundError as exc:
            return helpers.error(status_code=404, code="schedule_not_found", message=str(exc))
        except ValueError as exc:
            return helpers.error(status_code=400, code="invalid_schedule_trigger", message=str(exc))
        return helpers.success(result.to_dict())

    return router
