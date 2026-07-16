from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi import APIRouter, Path, Query, Request
from pydantic import BaseModel, ConfigDict, Field, StrictBool, field_validator

from framework.events.errors import EventContractError, EventStoreUnavailableError
from interfaces.api.deps import ApiRouteHelpers, ApiServices
from interfaces.models import ActorContext
from interfaces.services.event_delivery_operations_service import (
    EventOperationNotFoundError,
    MAX_OPERATOR_REASON_LENGTH,
)
from interfaces.services.event_operator_service import (
    EventOperationCapabilityUnavailableError,
    EventOperatorApplicationService,
)
from interfaces.services.event_reader_service import EventAuthorizationError


_MAX_PAGE_LIMIT = 1_000


class _ConfirmedMutationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    confirm: StrictBool

    @field_validator("confirm")
    @classmethod
    def _require_confirmation(cls, value: bool) -> bool:
        if value is not True:
            raise ValueError("confirm must be true")
        return value


class DeadLetterResolveRequest(_ConfirmedMutationRequest):
    operator_reason: str = Field(min_length=1, max_length=MAX_OPERATOR_REASON_LENGTH)


class DeadLetterRequeueRequest(_ConfirmedMutationRequest):
    subscription_id: str = Field(min_length=1, max_length=256)
    subscription_version: int = Field(ge=1)
    operator_reason: str = Field(min_length=1, max_length=MAX_OPERATOR_REASON_LENGTH)


EventOperatorCall = Callable[[EventOperatorApplicationService], dict[str, Any]]


def create_router(services: ApiServices, helpers: ApiRouteHelpers) -> APIRouter:
    router = APIRouter()

    @router.get("/api/v1/events/quarantine")
    def list_quarantine(
        request: Request,
        reason: str | None = Query(default=None, min_length=1, max_length=128),
        disposition: str | None = Query(default=None, min_length=1, max_length=128),
        cursor: str | None = Query(default=None, min_length=1, max_length=2_048),
        limit: int = Query(default=100, ge=1, le=_MAX_PAGE_LIMIT),
    ):
        return _invoke(
            request,
            services=services,
            helpers=helpers,
            allowed_query={"reason", "disposition", "cursor", "limit"},
            operation=lambda service: service.list_quarantine(
                reason=reason,
                disposition=disposition,
                cursor=cursor,
                limit=limit,
            ),
        )

    @router.get("/api/v1/events/quarantine/{quarantine_id}")
    def get_quarantine(
        request: Request,
        quarantine_id: str = Path(min_length=1, max_length=256),
    ):
        return _invoke(
            request,
            services=services,
            helpers=helpers,
            operation=lambda service: service.get_quarantine(quarantine_id),
        )

    @router.get("/api/v1/events/replay-reports")
    def list_replay_reports(
        request: Request,
        source_stream_id: str | None = Query(default=None, min_length=1, max_length=512),
        mode: str | None = Query(default=None, min_length=1, max_length=128),
        status: str | None = Query(default=None, min_length=1, max_length=128),
        cursor: str | None = Query(default=None, min_length=1, max_length=2_048),
        limit: int = Query(default=100, ge=1, le=_MAX_PAGE_LIMIT),
    ):
        return _invoke(
            request,
            services=services,
            helpers=helpers,
            allowed_query={"source_stream_id", "mode", "status", "cursor", "limit"},
            operation=lambda service: service.list_replay_reports(
                source_stream_id=source_stream_id,
                mode=mode,
                status=status,
                cursor=cursor,
                limit=limit,
            ),
        )

    @router.get("/api/v1/events/replay-reports/{replay_id}")
    def get_replay_report(
        request: Request,
        replay_id: str = Path(min_length=1, max_length=256),
    ):
        return _invoke(
            request,
            services=services,
            helpers=helpers,
            operation=lambda service: service.get_replay_report(replay_id),
        )

    @router.get("/api/v1/events/dead-letters")
    def list_dead_letters(
        request: Request,
        subscription_id: str | None = Query(default=None, min_length=1, max_length=256),
        subscription_version: int | None = Query(default=None, ge=1),
        disposition: str | None = Query(default=None, min_length=1, max_length=128),
        cursor: str | None = Query(default=None, min_length=1, max_length=2_048),
        limit: int = Query(default=100, ge=1, le=_MAX_PAGE_LIMIT),
    ):
        return _invoke(
            request,
            services=services,
            helpers=helpers,
            allowed_query={
                "subscription_id",
                "subscription_version",
                "disposition",
                "cursor",
                "limit",
            },
            operation=lambda service: service.list_dead_letters(
                subscription_id=subscription_id,
                subscription_version=subscription_version,
                disposition=disposition,
                cursor=cursor,
                limit=limit,
            ),
        )

    @router.get("/api/v1/events/dead-letters/{dead_letter_id}")
    def get_dead_letter(
        request: Request,
        dead_letter_id: str = Path(min_length=1, max_length=256),
    ):
        return _invoke(
            request,
            services=services,
            helpers=helpers,
            operation=lambda service: service.get_dead_letter(dead_letter_id),
        )

    @router.post("/api/v1/events/dead-letters/{dead_letter_id}/resolve")
    def resolve_dead_letter(
        body: DeadLetterResolveRequest,
        request: Request,
        dead_letter_id: str = Path(min_length=1, max_length=256),
    ):
        return _invoke(
            request,
            services=services,
            helpers=helpers,
            operation=lambda service: service.resolve_dead_letter(
                dead_letter_id,
                operator_reason=body.operator_reason,
            ),
        )

    @router.post("/api/v1/events/dead-letters/{dead_letter_id}/requeue")
    def requeue_dead_letter(
        body: DeadLetterRequeueRequest,
        request: Request,
        dead_letter_id: str = Path(min_length=1, max_length=256),
    ):
        return _invoke(
            request,
            services=services,
            helpers=helpers,
            operation=lambda service: service.requeue_dead_letter(
                dead_letter_id,
                subscription_id=body.subscription_id,
                subscription_version=body.subscription_version,
                operator_reason=body.operator_reason,
                idempotency_acknowledged=True,
            ),
        )

    @router.get(
        "/api/v1/events/consumers/{subscription_id}/versions/"
        "{subscription_version}/status"
    )
    def get_consumer_status(
        request: Request,
        subscription_id: str = Path(min_length=1, max_length=256),
        subscription_version: int = Path(ge=1),
        stream_id: str = Query(min_length=1, max_length=512),
    ):
        return _invoke(
            request,
            services=services,
            helpers=helpers,
            allowed_query={"stream_id"},
            operation=lambda service: service.get_consumer_status(
                subscription_id=subscription_id,
                subscription_version=subscription_version,
                stream_id=stream_id,
            ),
        )

    @router.get("/api/v1/events/projections/runs/{run_id}/status")
    def get_projection_status(
        request: Request,
        run_id: str = Path(min_length=1, max_length=256),
    ):
        return _invoke(
            request,
            services=services,
            helpers=helpers,
            operation=lambda service: service.get_projection_status(run_id),
        )

    return router


def _invoke(
    request: Request,
    *,
    services: ApiServices,
    helpers: ApiRouteHelpers,
    operation: EventOperatorCall,
    allowed_query: set[str] | None = None,
):
    actor = getattr(request.state, "actor_context", None)
    if not isinstance(actor, ActorContext):
        return helpers.error(
            status_code=401,
            code="unauthorized",
            message="authenticated event operator required",
            user_action_required=True,
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        _validate_query_parameters(request, allowed=allowed_query or set())
        result = operation(services.event_operator_service_factory(actor))
        if not isinstance(result, dict):
            raise EventContractError("event operator service returned an invalid response")
    except EventAuthorizationError:
        return helpers.error(
            status_code=403,
            code="forbidden",
            message="event operator action is not authorized",
            user_action_required=True,
        )
    except EventOperationNotFoundError:
        return helpers.error(
            status_code=404,
            code="event_operator_resource_not_found",
            message="event operator resource not found",
        )
    except EventOperationCapabilityUnavailableError:
        return helpers.error(
            status_code=503,
            code="event_operator_capability_unavailable",
            message="event operator capability is unavailable",
            user_action_required=True,
        )
    except EventStoreUnavailableError:
        return helpers.error(
            status_code=503,
            code="event_store_unavailable",
            message="event store is unavailable",
            retryable=True,
        )
    except EventContractError:
        return helpers.error(
            status_code=409,
            code="event_operator_contract_conflict",
            message="event operator data conflicts with the durable event contract",
        )
    except ValueError as exc:
        return helpers.error(
            status_code=400,
            code="invalid_event_operator_request",
            message=str(exc),
            user_action_required=True,
        )
    return helpers.success(result)


def _validate_query_parameters(request: Request, *, allowed: set[str]) -> None:
    unexpected = sorted(set(request.query_params.keys()).difference(allowed))
    if unexpected:
        names = ", ".join(unexpected)
        raise ValueError(f"unexpected query parameters: {names}")


__all__ = [
    "DeadLetterRequeueRequest",
    "DeadLetterResolveRequest",
    "create_router",
]
