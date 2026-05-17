from __future__ import annotations

from fastapi import APIRouter

from core.framework.workers.schedule_store import ScheduleNotFoundError, ScheduleRecord
from core.framework.workers.scheduler import ScheduleSpec
from interfaces.api.deps import ApiRouteHelpers, ApiServices
from interfaces.models import DailyScheduleRequest, ManualScheduleTriggerRequest, ScheduleTickRequest


def create_router(services: ApiServices, helpers: ApiRouteHelpers) -> APIRouter:
    router = APIRouter()

    @router.get("/api/v1/schedules")
    def list_schedules(include_disabled: bool = False):
        result = services.schedule_service_factory().list_schedules(enabled_only=not include_disabled)
        return helpers.success(result.to_dict())

    @router.post("/api/v1/schedules/daily")
    def upsert_daily_schedule(request: DailyScheduleRequest):
        try:
            spec = ScheduleSpec(
                schedule_id=request.schedule_id,
                name=request.name,
                trigger_type=request.trigger_type,
                task_type="daily_intelligence.run",
                payload_template={
                    "profile": request.profile,
                    "topic": request.topic,
                    "source_limit": request.source_limit,
                },
                queue_name=request.queue_name,
                interval_seconds=(
                    request.interval_seconds if request.trigger_type == "interval" else None
                ),
                run_at=request.run_at if request.trigger_type == "interval" else None,
            )
        except ValueError as exc:
            return helpers.error(status_code=400, code="invalid_schedule", message=str(exc))
        record = ScheduleRecord(spec=spec, next_run_at=spec.run_at)
        result = services.schedule_service_factory().upsert_schedule(record)
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
