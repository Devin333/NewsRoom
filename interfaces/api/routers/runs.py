from __future__ import annotations

from fastapi import APIRouter, Header, Path, Request
from fastapi.responses import StreamingResponse

from framework.agent.artifacts import (
    ArtifactChecksumMismatchError,
    ArtifactPathError,
    ArtifactStoreMetadataError,
    ArtifactStoreRequiredError,
)
from framework.events.errors import EventStoreUnavailableError
from interfaces.api.deps import ApiRouteHelpers, ApiServices, get_actor_context
from interfaces.models import ActorContext, GraphRunCancellationRequest


_GRAPH_RUNS_PREFIX = "/api/v2/graph-runs"
_ARTIFACT_INTEGRITY_HTTP_CONTRACT = {
    ArtifactChecksumMismatchError: (409, "artifact_checksum_mismatch"),
    ArtifactStoreMetadataError: (409, "artifact_metadata_corrupt"),
    ArtifactStoreRequiredError: (500, "artifact_store_unavailable"),
}
_ARTIFACT_INTEGRITY_ERRORS = tuple(_ARTIFACT_INTEGRITY_HTTP_CONTRACT)


def create_router(services: ApiServices, helpers: ApiRouteHelpers) -> APIRouter:
    router = APIRouter()

    @router.get(_GRAPH_RUNS_PREFIX)
    def list_runs(
        limit: int = 20,
        offset: int = 0,
        status: str | None = None,
        graph_id: str | None = None,
    ):
        try:
            result = services.graph_run_inspection_service_factory().list_runs(
                limit=limit,
                offset=offset,
                status=status,
                graph_id=graph_id,
            )
        except ValueError as exc:
            return helpers.error(
                status_code=400,
                code="invalid_graph_run_list_request",
                message=str(exc),
            )
        return helpers.success(result.to_dict())

    @router.get(f"{_GRAPH_RUNS_PREFIX}/catalog/health")
    def get_run_catalog_health():
        return helpers.success(
            services.graph_run_inspection_service_factory()
            .get_catalog_health()
            .to_dict()
        )

    @router.get(f"{_GRAPH_RUNS_PREFIX}/compare")
    def compare_runs(base_run_id: str, target_run_id: str):
        try:
            result = services.graph_run_inspection_service_factory().compare_runs(
                base_run_id,
                target_run_id,
            )
        except FileNotFoundError as exc:
            return helpers.error(
                status_code=404,
                code="graph_run_not_found",
                message=str(exc),
                user_action_required=True,
            )
        except EventStoreUnavailableError:
            return _event_store_unavailable_error(helpers)
        except ValueError as exc:
            return helpers.error(
                status_code=400,
                code="invalid_graph_run_compare_request",
                message=str(exc),
            )
        return helpers.success(result.to_dict())

    @router.get(f"{_GRAPH_RUNS_PREFIX}/{{run_id}}")
    def get_run(run_id: str = Path(min_length=1)):
        try:
            result = services.graph_run_inspection_service_factory().get_run(run_id)
        except FileNotFoundError as exc:
            return helpers.error(
                status_code=404,
                code="graph_run_not_found",
                message=str(exc),
                user_action_required=True,
            )
        except ValueError as exc:
            return helpers.error(status_code=400, code="invalid_graph_run_id", message=str(exc))
        return helpers.success(result.to_dict())

    @router.get(f"{_GRAPH_RUNS_PREFIX}/{{run_id}}/manifest")
    def get_run_manifest(run_id: str = Path(min_length=1)):
        return get_run(run_id)

    @router.get(f"{_GRAPH_RUNS_PREFIX}/{{run_id}}/events")
    def get_run_events(
        run_id: str = Path(min_length=1),
        event_type: str | None = None,
        node_instance_id: str | None = None,
        limit: int | None = None,
        offset: int = 0,
        sequence_cursor: str | None = None,
    ):
        try:
            result = services.graph_run_inspection_service_factory().get_run_events(
                run_id,
                event_type=event_type,
                node_instance_id=node_instance_id,
                limit=limit,
                offset=offset,
                sequence_cursor=sequence_cursor,
            )
        except FileNotFoundError as exc:
            return helpers.error(
                status_code=404,
                code="graph_run_events_not_found",
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
            return helpers.error(status_code=400, code="invalid_graph_run_events_request", message=str(exc))
        return helpers.success(result.to_dict())

    @router.get(f"{_GRAPH_RUNS_PREFIX}/{{run_id}}/steps")
    def get_run_steps(run_id: str = Path(min_length=1)):
        try:
            result = services.graph_run_inspection_service_factory().get_run_steps(run_id)
        except FileNotFoundError as exc:
            return helpers.error(status_code=404, code="graph_run_not_found", message=str(exc))
        except ValueError as exc:
            return helpers.error(status_code=400, code="invalid_graph_run_steps_request", message=str(exc))
        return helpers.success(result.to_dict())

    @router.get(
        f"{_GRAPH_RUNS_PREFIX}/{{run_id}}/events/stream",
        response_class=StreamingResponse,
    )
    def stream_run_events(
        run_id: str = Path(min_length=1),
        limit: int | None = None,
        sequence_cursor: str | None = None,
        last_event_id: str | None = Header(default=None, alias="Last-Event-ID"),
    ):
        try:
            result = services.graph_run_inspection_service_factory().get_run_events_for_sse(
                run_id,
                limit=limit,
                sequence_cursor=sequence_cursor,
                last_event_id=last_event_id,
            )
        except FileNotFoundError as exc:
            return helpers.error(status_code=404, code="graph_run_events_not_found", message=str(exc))
        except EventStoreUnavailableError as exc:
            return helpers.error(status_code=503, code="event_store_unavailable", message=str(exc), retryable=True)
        except ValueError as exc:
            return helpers.error(status_code=400, code="invalid_graph_run_events_request", message=str(exc))
        return StreamingResponse(
            helpers.run_events_sse_frames(result.to_dict()),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @router.get(f"{_GRAPH_RUNS_PREFIX}/{{run_id}}/replay")
    def replay_run(run_id: str = Path(min_length=1)):
        try:
            result = services.graph_run_inspection_service_factory().replay_run(run_id)
        except ArtifactPathError as exc:
            return helpers.error(status_code=400, code="invalid_graph_replay_request", message=str(exc))
        except _ARTIFACT_INTEGRITY_ERRORS as exc:
            return _artifact_integrity_error(exc, helpers=helpers)
        except FileNotFoundError as exc:
            return helpers.error(status_code=404, code="graph_run_not_found", message=str(exc))
        except EventStoreUnavailableError:
            return _event_store_unavailable_error(helpers)
        except ValueError as exc:
            return helpers.error(status_code=400, code="invalid_graph_replay_request", message=str(exc))
        return helpers.success(result.to_dict())

    @router.get(f"{_GRAPH_RUNS_PREFIX}/{{run_id}}/diagnostics")
    def get_run_diagnostics(run_id: str = Path(min_length=1)):
        try:
            result = services.graph_run_inspection_service_factory().get_run_diagnostics(run_id)
        except FileNotFoundError as exc:
            return helpers.error(status_code=404, code="graph_run_not_found", message=str(exc))
        except EventStoreUnavailableError:
            return _event_store_unavailable_error(helpers)
        except ValueError as exc:
            return helpers.error(status_code=400, code="invalid_graph_run_diagnostics_request", message=str(exc))
        return helpers.success(result.to_dict())

    @router.get(f"{_GRAPH_RUNS_PREFIX}/{{run_id}}/health")
    def get_run_health(run_id: str = Path(min_length=1)):
        try:
            result = services.graph_run_inspection_service_factory().get_run_health(run_id)
        except FileNotFoundError as exc:
            return helpers.error(status_code=404, code="graph_run_not_found", message=str(exc))
        except EventStoreUnavailableError:
            return _event_store_unavailable_error(helpers)
        except ValueError as exc:
            return helpers.error(status_code=400, code="invalid_graph_run_health_request", message=str(exc))
        return helpers.success(result.to_dict())

    @router.get(f"{_GRAPH_RUNS_PREFIX}/{{run_id}}/lineage")
    def list_run_lineage(run_id: str = Path(min_length=1)):
        try:
            result = services.storage_service_factory().list_lineage(run_id)
        except ValueError as exc:
            return helpers.error(status_code=400, code="invalid_lineage_request", message=str(exc))
        return helpers.success(result.to_dict())

    @router.get(f"{_GRAPH_RUNS_PREFIX}/{{run_id}}/lineage/upstream")
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

    @router.get(f"{_GRAPH_RUNS_PREFIX}/{{run_id}}/lineage/downstream")
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

    @router.get(f"{_GRAPH_RUNS_PREFIX}/{{run_id}}/artifacts")
    def list_artifacts(run_id: str = Path(min_length=1)):
        try:
            result = services.artifact_service_factory().list_artifacts(run_id)
        except FileNotFoundError as exc:
            return helpers.error(status_code=404, code="graph_run_not_found", message=str(exc))
        except ValueError as exc:
            return helpers.error(status_code=400, code="invalid_artifact_path", message=str(exc))
        return helpers.success(result.to_dict())

    @router.get(f"{_GRAPH_RUNS_PREFIX}/{{run_id}}/artifacts/{{artifact_key}}")
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

    @router.post(f"{_GRAPH_RUNS_PREFIX}/{{run_id}}/cancel")
    def cancel_run(
        request: Request,
        payload: GraphRunCancellationRequest,
        run_id: str = Path(min_length=1),
    ):
        actor = get_actor_context(request)
        if not isinstance(actor, ActorContext) or actor.actor_id == "anonymous":
            return helpers.error(
                status_code=401,
                code="unauthorized",
                message="authenticated Graph run actor required",
                user_action_required=True,
                headers={"WWW-Authenticate": "Bearer"},
            )
        try:
            result = services.graph_run_operation_service_factory().cancel_run(
                run_id,
                reason_code=payload.reason_code,
                cancellation_id=payload.cancellation_id,
                actor=actor,
            )
        except FileNotFoundError as exc:
            return helpers.error(status_code=404, code="graph_run_not_found", message=str(exc))
        except PermissionError as exc:
            return helpers.error(status_code=403, code="forbidden", message=str(exc))
        except RuntimeError as exc:
            return helpers.error(status_code=503, code="graph_operation_unavailable", message=str(exc), retryable=True)
        except ValueError as exc:
            return helpers.error(status_code=400, code="invalid_graph_cancellation_request", message=str(exc))
        return helpers.success(result.to_dict())

    return router


def _event_store_unavailable_error(helpers: ApiRouteHelpers):
    return helpers.error(
        status_code=503,
        code="event_store_unavailable",
        message="event store is unavailable",
        retryable=True,
    )


def _artifact_integrity_error(exc: Exception, *, helpers: ApiRouteHelpers):
    for error_type, (status_code, code) in _ARTIFACT_INTEGRITY_HTTP_CONTRACT.items():
        if isinstance(exc, error_type):
            return helpers.error(status_code=status_code, code=code, message=str(exc))
    raise TypeError(f"unsupported artifact integrity error: {type(exc).__name__}")


__all__ = ["create_router"]
