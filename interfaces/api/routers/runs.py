from __future__ import annotations

from fastapi import APIRouter, Header
from fastapi.responses import StreamingResponse

from framework.agent.artifacts import (
    ArtifactChecksumMismatchError,
    ArtifactPathError,
    ArtifactStoreMetadataError,
    ArtifactStoreRequiredError,
)
from framework.events.errors import EventStoreUnavailableError
from interfaces.api.deps import ApiRouteHelpers, ApiServices
from interfaces.models import (
    RunMarkBlockedResolvedRequest,
    RunOperationRequest,
    RunRerunFromStepRequest,
    RunResumeWithPatchRequest,
    RunSkipStepRequest,
)


def create_router(services: ApiServices, helpers: ApiRouteHelpers) -> APIRouter:
    router = APIRouter()

    @router.get("/api/v1/runs")
    def list_runs(
        limit: int = 20,
        offset: int = 0,
        status: str | None = None,
        workflow_id: str | None = None,
        profile: str | None = None,
    ):
        try:
            inspection_service = services.run_inspection_service_factory()
            if offset or status is not None or workflow_id is not None or profile is not None:
                result = inspection_service.list_runs(
                    limit=limit,
                    offset=offset,
                    status=status,
                    workflow_id=workflow_id,
                    profile=profile,
                )
            else:
                result = inspection_service.list_runs(limit=limit)
        except ValueError as exc:
            return helpers.error(status_code=400, code="invalid_run_list_request", message=str(exc))
        return helpers.success(result.to_dict())

    @router.get("/api/v1/runs/catalog/health")
    def get_run_catalog_health():
        return helpers.success(services.run_inspection_service_factory().get_catalog_health().to_dict())

    @router.get("/api/v1/runs/compare")
    def compare_runs(base_run_id: str, target_run_id: str):
        try:
            result = services.run_inspection_service_factory().compare_runs(base_run_id, target_run_id)
        except FileNotFoundError as exc:
            return helpers.error(
                status_code=404,
                code="run_not_found",
                message=str(exc),
                user_action_required=True,
            )
        except EventStoreUnavailableError:
            return _event_store_unavailable_error(helpers)
        except ValueError as exc:
            return helpers.error(status_code=400, code="invalid_run_compare_request", message=str(exc))
        return helpers.success(result.to_dict())

    @router.get("/api/v1/runs/{run_id}")
    def get_run(run_id: str):
        try:
            result = services.run_inspection_service_factory().get_run(run_id)
        except FileNotFoundError as exc:
            return helpers.error(
                status_code=404,
                code="run_not_found",
                message=str(exc),
                user_action_required=True,
            )
        except ValueError as exc:
            return helpers.error(status_code=400, code="invalid_run_id", message=str(exc))
        return helpers.success(result.to_dict())

    @router.get("/api/v1/runs/{run_id}/manifest")
    def get_run_manifest(run_id: str):
        return get_run(run_id)

    @router.get("/api/v1/runs/{run_id}/events")
    def get_run_events(
        run_id: str,
        event_type: str | None = None,
        step_id: str | None = None,
        limit: int | None = None,
        offset: int = 0,
        sequence_cursor: str | None = None,
    ):
        try:
            inspection_service = services.run_inspection_service_factory()
            if event_type is not None or step_id is not None or offset or sequence_cursor:
                result = inspection_service.get_run_events(
                    run_id,
                    event_type=event_type,
                    step_id=step_id,
                    limit=limit,
                    offset=offset,
                    sequence_cursor=sequence_cursor,
                )
            else:
                result = inspection_service.get_run_events(run_id, limit=limit)
        except FileNotFoundError as exc:
            return helpers.error(
                status_code=404,
                code="run_events_not_found",
                message=str(exc),
                user_action_required=True,
            )
        except EventStoreUnavailableError as exc:
            return helpers.error(
                status_code=503,
                code="event_store_unavailable",
                message=str(exc),
                retryable=True,
            )
        except ValueError as exc:
            return helpers.error(status_code=400, code="invalid_run_events_request", message=str(exc))
        return helpers.success(result.to_dict())

    @router.get("/api/v1/runs/{run_id}/steps")
    def get_run_steps(run_id: str):
        try:
            result = services.run_inspection_service_factory().get_run_steps(run_id)
        except FileNotFoundError as exc:
            return helpers.error(
                status_code=404,
                code="run_not_found",
                message=str(exc),
                user_action_required=True,
            )
        except ValueError as exc:
            return helpers.error(status_code=400, code="invalid_run_steps_request", message=str(exc))
        return helpers.success(result.to_dict())

    @router.get(
        "/api/v1/runs/{run_id}/progress",
        responses={
            200: {
                "description": "Run progress as Server-Sent Events.",
                "content": {"text/event-stream": {"schema": {"type": "string"}}},
            }
        },
    )
    def stream_run_progress(
        run_id: str,
        limit: int | None = None,
        sequence_cursor: str | None = None,
        last_event_id: str | None = Header(default=None, alias="Last-Event-ID"),
    ):
        try:
            inspection_service = services.run_inspection_service_factory()
            if hasattr(inspection_service, "get_run_events_for_sse"):
                result = inspection_service.get_run_events_for_sse(
                    run_id,
                    limit=limit,
                    sequence_cursor=sequence_cursor,
                    last_event_id=last_event_id,
                )
            elif last_event_id is not None:
                raise ValueError("Last-Event-ID is not supported by this inspection service")
            elif sequence_cursor is None:
                result = inspection_service.get_run_events(run_id, limit=limit)
            else:
                result = inspection_service.get_run_events(
                    run_id,
                    limit=limit,
                    sequence_cursor=sequence_cursor,
                )
        except (AttributeError, FileNotFoundError) as exc:
            return helpers.error(
                status_code=404,
                code="run_progress_not_found",
                message=str(exc),
                user_action_required=True,
            )
        except EventStoreUnavailableError as exc:
            return helpers.error(
                status_code=503,
                code="event_store_unavailable",
                message=str(exc),
                retryable=True,
            )
        except ValueError as exc:
            return helpers.error(status_code=400, code="invalid_run_progress_request", message=str(exc))
        return StreamingResponse(
            helpers.run_progress_sse_frames(result.to_dict()),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @router.get(
        "/api/v1/runs/{run_id}/events/stream",
        responses={
            200: {
                "description": "Run events as Server-Sent Events.",
                "content": {"text/event-stream": {"schema": {"type": "string"}}},
            }
        },
    )
    def stream_run_events(
        run_id: str,
        limit: int | None = None,
        sequence_cursor: str | None = None,
        last_event_id: str | None = Header(default=None, alias="Last-Event-ID"),
    ):
        try:
            inspection_service = services.run_inspection_service_factory()
            if hasattr(inspection_service, "get_run_events_for_sse"):
                result = inspection_service.get_run_events_for_sse(
                    run_id,
                    limit=limit,
                    sequence_cursor=sequence_cursor,
                    last_event_id=last_event_id,
                )
            elif last_event_id is not None:
                raise ValueError("Last-Event-ID is not supported by this inspection service")
            elif sequence_cursor is None:
                result = inspection_service.get_run_events(run_id, limit=limit)
            else:
                result = inspection_service.get_run_events(
                    run_id,
                    limit=limit,
                    sequence_cursor=sequence_cursor,
                )
        except FileNotFoundError as exc:
            return helpers.error(
                status_code=404,
                code="run_events_not_found",
                message=str(exc),
                user_action_required=True,
            )
        except EventStoreUnavailableError as exc:
            return helpers.error(
                status_code=503,
                code="event_store_unavailable",
                message=str(exc),
                retryable=True,
            )
        except ValueError as exc:
            return helpers.error(status_code=400, code="invalid_run_events_request", message=str(exc))
        return StreamingResponse(
            helpers.run_events_sse_frames(result.to_dict()),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @router.get("/api/v1/runs/{run_id}/replay")
    def replay_run(run_id: str):
        try:
            result = services.run_inspection_service_factory().replay_run(run_id)
        except ArtifactPathError as exc:
            return helpers.error(
                status_code=400,
                code="invalid_run_replay_request",
                message=str(exc),
            )
        except _ARTIFACT_INTEGRITY_ERRORS as exc:
            return _artifact_integrity_error(exc, helpers=helpers)
        except FileNotFoundError as exc:
            return helpers.error(
                status_code=404,
                code="run_not_found",
                message=str(exc),
                user_action_required=True,
            )
        except EventStoreUnavailableError:
            return _event_store_unavailable_error(helpers)
        except ValueError as exc:
            return helpers.error(status_code=400, code="invalid_run_replay_request", message=str(exc))
        return helpers.success(result.to_dict())

    @router.get("/api/v1/runs/{run_id}/diagnostics")
    def get_run_diagnostics(run_id: str):
        try:
            result = services.run_inspection_service_factory().get_run_diagnostics(run_id)
        except FileNotFoundError as exc:
            return helpers.error(
                status_code=404,
                code="run_not_found",
                message=str(exc),
                user_action_required=True,
            )
        except EventStoreUnavailableError:
            return _event_store_unavailable_error(helpers)
        except ValueError as exc:
            return helpers.error(status_code=400, code="invalid_run_diagnostics_request", message=str(exc))
        return helpers.success(result.to_dict())

    @router.get("/api/v1/runs/{run_id}/health")
    def get_run_health(run_id: str):
        try:
            result = services.run_inspection_service_factory().get_run_health(run_id)
        except FileNotFoundError as exc:
            return helpers.error(
                status_code=404,
                code="run_not_found",
                message=str(exc),
                user_action_required=True,
            )
        except EventStoreUnavailableError:
            return _event_store_unavailable_error(helpers)
        except ValueError as exc:
            return helpers.error(status_code=400, code="invalid_run_health_request", message=str(exc))
        return helpers.success(result.to_dict())

    @router.get("/api/v1/runs/{run_id}/lineage")
    def list_run_lineage(run_id: str):
        try:
            result = services.storage_service_factory().list_lineage(run_id)
        except ValueError as exc:
            return helpers.error(status_code=400, code="invalid_lineage_request", message=str(exc))
        return helpers.success(result.to_dict())

    @router.get("/api/v1/runs/{run_id}/lineage/upstream")
    def run_lineage_upstream(run_id: str, target_type: str, target_id: str):
        try:
            result = services.storage_service_factory().lineage_upstream(
                run_id=run_id,
                target_type=target_type,
                target_id=target_id,
            )
        except ValueError as exc:
            return helpers.error(status_code=400, code="invalid_lineage_request", message=str(exc))
        return helpers.success(result.to_dict())

    @router.get("/api/v1/runs/{run_id}/lineage/downstream")
    def run_lineage_downstream(run_id: str, source_type: str, source_id: str):
        try:
            result = services.storage_service_factory().lineage_downstream(
                run_id=run_id,
                source_type=source_type,
                source_id=source_id,
            )
        except ValueError as exc:
            return helpers.error(status_code=400, code="invalid_lineage_request", message=str(exc))
        return helpers.success(result.to_dict())

    @router.get("/api/v1/runs/{run_id}/artifacts")
    def list_artifacts(run_id: str):
        try:
            result = services.artifact_service_factory().list_artifacts(run_id)
        except FileNotFoundError as exc:
            return helpers.error(status_code=404, code="run_not_found", message=str(exc))
        except ValueError as exc:
            return helpers.error(status_code=400, code="invalid_artifact_path", message=str(exc))
        return helpers.success(result.to_dict())

    @router.get("/api/v1/runs/{run_id}/artifacts/{artifact_key}")
    def get_artifact(run_id: str, artifact_key: str):
        try:
            result = services.artifact_service_factory().get_artifact(run_id, artifact_key)
        except ArtifactPathError as exc:
            return helpers.error(status_code=400, code="invalid_artifact_path", message=str(exc))
        except _ARTIFACT_INTEGRITY_ERRORS as exc:
            return _artifact_integrity_error(exc, helpers=helpers)
        except FileNotFoundError as exc:
            return helpers.error(status_code=404, code="artifact_not_found", message=str(exc))
        except ValueError as exc:
            return helpers.error(status_code=400, code="invalid_artifact_path", message=str(exc))
        return helpers.success(result.to_dict())

    @router.get("/api/v1/artifacts")
    def list_artifacts_by_run(run_id: str):
        return list_artifacts(run_id)

    @router.get("/api/v1/artifacts/{artifact_id}")
    def get_artifact_by_id(artifact_id: str, run_id: str | None = None):
        try:
            resolved_run_id, artifact_key = helpers.artifact_lookup_ids(artifact_id, run_id)
            result = services.artifact_service_factory().get_artifact(resolved_run_id, artifact_key)
        except ArtifactPathError as exc:
            return helpers.error(status_code=400, code="invalid_artifact_id", message=str(exc))
        except _ARTIFACT_INTEGRITY_ERRORS as exc:
            return _artifact_integrity_error(exc, helpers=helpers)
        except FileNotFoundError as exc:
            return helpers.error(status_code=404, code="artifact_not_found", message=str(exc))
        except ValueError as exc:
            return helpers.error(status_code=400, code="invalid_artifact_id", message=str(exc))
        return helpers.success(result.to_dict())

    @router.post("/api/v1/runs/{run_id}/operations/cancel")
    def cancel_run(run_id: str, request: RunOperationRequest | None = None):
        actual_request = request or RunOperationRequest()
        try:
            result = services.run_operation_service_factory().cancel_run(
                run_id,
                reason=actual_request.reason,
                actor_id=actual_request.actor_id,
                metadata=actual_request.metadata,
            )
        except FileNotFoundError as exc:
            return helpers.error(status_code=404, code="run_not_found", message=str(exc))
        except ValueError as exc:
            return helpers.error(status_code=400, code="invalid_run_operation_request", message=str(exc))
        return helpers.success(result.to_dict())

    @router.post("/api/v1/runs/{run_id}/operations/rerun-from-step")
    def rerun_from_step(run_id: str, request: RunRerunFromStepRequest):
        try:
            result = services.run_operation_service_factory().rerun_from_step(
                run_id,
                step_id=request.step_id,
                actor_id=request.actor_id,
                metadata=request.metadata,
            )
        except FileNotFoundError as exc:
            return helpers.error(status_code=404, code="run_not_found", message=str(exc))
        except ValueError as exc:
            return helpers.error(status_code=400, code="invalid_run_operation_request", message=str(exc))
        return helpers.success(result.to_dict())

    @router.post("/api/v1/runs/{run_id}/operations/resume-with-patch")
    def resume_with_patch(run_id: str, request: RunResumeWithPatchRequest):
        try:
            result = services.run_operation_service_factory().resume_with_patch(
                run_id,
                patch=request.patch,
                actor_id=request.actor_id,
                metadata=request.metadata,
            )
        except FileNotFoundError as exc:
            return helpers.error(status_code=404, code="run_not_found", message=str(exc))
        except ValueError as exc:
            return helpers.error(status_code=400, code="invalid_run_operation_request", message=str(exc))
        return helpers.success(result.to_dict())

    @router.post("/api/v1/runs/{run_id}/operations/skip-step")
    def skip_step(run_id: str, request: RunSkipStepRequest):
        try:
            result = services.run_operation_service_factory().skip_step(
                run_id,
                step_id=request.step_id,
                reason=request.reason,
                actor_id=request.actor_id,
                metadata=request.metadata,
            )
        except FileNotFoundError as exc:
            return helpers.error(status_code=404, code="run_not_found", message=str(exc))
        except ValueError as exc:
            return helpers.error(status_code=400, code="invalid_run_operation_request", message=str(exc))
        return helpers.success(result.to_dict())

    @router.post("/api/v1/runs/{run_id}/operations/mark-blocked-resolved")
    def mark_blocked_resolved(run_id: str, request: RunMarkBlockedResolvedRequest):
        try:
            result = services.run_operation_service_factory().mark_blocked_resolved(
                run_id,
                reason=request.reason,
                resolved_by=request.resolved_by,
                resolution_type=request.resolution_type,
                actor_id=request.actor_id,
                metadata=request.metadata,
            )
        except FileNotFoundError as exc:
            return helpers.error(status_code=404, code="run_not_found", message=str(exc))
        except ValueError as exc:
            return helpers.error(status_code=400, code="invalid_run_operation_request", message=str(exc))
        return helpers.success(result.to_dict())

    return router


def _event_store_unavailable_error(helpers: ApiRouteHelpers):
    return helpers.error(
        status_code=503,
        code="event_store_unavailable",
        message="event store is unavailable",
        retryable=True,
    )


_ARTIFACT_INTEGRITY_HTTP_CONTRACT = {
    ArtifactChecksumMismatchError: (409, "artifact_checksum_mismatch"),
    ArtifactStoreMetadataError: (409, "artifact_metadata_corrupt"),
    ArtifactStoreRequiredError: (500, "artifact_store_unavailable"),
}
_ARTIFACT_INTEGRITY_ERRORS = tuple(_ARTIFACT_INTEGRITY_HTTP_CONTRACT)


def _artifact_integrity_error(
    exc: Exception,
    *,
    helpers: ApiRouteHelpers,
):
    for error_type, (status_code, code) in _ARTIFACT_INTEGRITY_HTTP_CONTRACT.items():
        if isinstance(exc, error_type):
            return helpers.error(status_code=status_code, code=code, message=str(exc))
    raise TypeError(f"unsupported artifact integrity error: {type(exc).__name__}")
