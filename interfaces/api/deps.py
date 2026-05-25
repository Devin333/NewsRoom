from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from fastapi import Request

from interfaces.models import ActorContext, actor_context_from_headers
from interfaces.services.approval_service import ApprovalApplicationService
from interfaces.services.artifact_service import ArtifactInspectionService
from interfaces.services.auth_service import AuthApplicationService
from interfaces.services.board_service import BoardApplicationService
from interfaces.services.diagnose_service import DiagnosticApplicationService
from interfaces.services.entity_service import EntityTrackingApplicationService
from interfaces.services.memory_service import MemoryApplicationService
from interfaces.services.mcp_service import MCPApplicationService
from interfaces.services.paper_service import PapersApplicationService
from interfaces.services.paper_user_state_service import PaperUserStateApplicationService
from interfaces.services.report_service import ReportApplicationService
from interfaces.services.run_inspection_service import RunInspectionService
from interfaces.services.run_operation_service import RunOperationApplicationService
from interfaces.services.run_service import RunApplicationService
from interfaces.services.schedule_service import ScheduleApplicationService
from interfaces.services.source_service import SourceApplicationService
from interfaces.services.storage_service import StorageApplicationService
from interfaces.services.subscription_service import SubscriptionApplicationService
from interfaces.services.worker_service import WorkerApplicationService


WorkerServiceFactory = Callable[[], WorkerApplicationService]
RunServiceFactory = Callable[[], RunApplicationService]
RunOperationServiceFactory = Callable[[], RunOperationApplicationService]
ReportServiceFactory = Callable[[], ReportApplicationService]
MemoryServiceFactory = Callable[[], MemoryApplicationService]
DiagnosticServiceFactory = Callable[[], DiagnosticApplicationService]
SourceServiceFactory = Callable[[], SourceApplicationService]
EntityServiceFactory = Callable[[], EntityTrackingApplicationService]
SubscriptionServiceFactory = Callable[[], SubscriptionApplicationService]
MCPServiceFactory = Callable[[], MCPApplicationService]
RunInspectionServiceFactory = Callable[[], RunInspectionService]
ArtifactInspectionServiceFactory = Callable[[], ArtifactInspectionService]
StorageServiceFactory = Callable[[], StorageApplicationService]
ScheduleServiceFactory = Callable[[], ScheduleApplicationService]
ApprovalServiceFactory = Callable[[], ApprovalApplicationService]
BoardServiceFactory = Callable[[], BoardApplicationService]
PapersServiceFactory = Callable[[], PapersApplicationService]
AuthServiceFactory = Callable[[], AuthApplicationService]
PaperUserStateServiceFactory = Callable[[], PaperUserStateApplicationService]


@dataclass(frozen=True)
class ApiServices:
    worker_service_factory: WorkerServiceFactory
    run_service_factory: RunServiceFactory
    run_operation_service_factory: RunOperationServiceFactory
    report_service_factory: ReportServiceFactory
    memory_service_factory: MemoryServiceFactory
    diagnostic_service_factory: DiagnosticServiceFactory
    source_service_factory: SourceServiceFactory
    entity_service_factory: EntityServiceFactory
    subscription_service_factory: SubscriptionServiceFactory
    mcp_service_factory: MCPServiceFactory
    run_inspection_service_factory: RunInspectionServiceFactory
    artifact_service_factory: ArtifactInspectionServiceFactory
    storage_service_factory: StorageServiceFactory
    schedule_service_factory: ScheduleServiceFactory
    approval_service_factory: ApprovalServiceFactory
    board_service_factory: BoardServiceFactory
    papers_service_factory: PapersServiceFactory
    auth_service_factory: AuthServiceFactory
    paper_user_state_service_factory: PaperUserStateServiceFactory


@dataclass(frozen=True)
class ApiRouteHelpers:
    success: Callable[[dict[str, Any]], dict[str, Any]]
    error: Callable[..., Any]
    model_to_dict: Callable[[Any], dict[str, Any]]
    run_result_response: Callable[[Any], dict[str, Any]]
    provided_values: Callable[..., dict[str, Any]]
    artifact_lookup_ids: Callable[[str, str | None], tuple[str, str]]
    approval_decision_response: Callable[[Callable[[], Any]], Any]
    run_progress_sse_frames: Callable[[dict[str, Any]], Any]
    run_events_sse_frames: Callable[[dict[str, Any]], Any]


def build_api_services(
    *,
    worker_service_factory: WorkerServiceFactory = WorkerApplicationService,
    run_service_factory: RunServiceFactory = RunApplicationService,
    run_operation_service_factory: RunOperationServiceFactory = RunOperationApplicationService,
    report_service_factory: ReportServiceFactory = ReportApplicationService,
    memory_service_factory: MemoryServiceFactory = MemoryApplicationService,
    diagnostic_service_factory: DiagnosticServiceFactory = DiagnosticApplicationService,
    source_service_factory: SourceServiceFactory = SourceApplicationService,
    entity_service_factory: EntityServiceFactory = EntityTrackingApplicationService,
    subscription_service_factory: SubscriptionServiceFactory = SubscriptionApplicationService,
    mcp_service_factory: MCPServiceFactory = MCPApplicationService,
    run_inspection_service_factory: RunInspectionServiceFactory = RunInspectionService,
    artifact_service_factory: ArtifactInspectionServiceFactory = ArtifactInspectionService,
    storage_service_factory: StorageServiceFactory = StorageApplicationService,
    schedule_service_factory: ScheduleServiceFactory = ScheduleApplicationService,
    approval_service_factory: ApprovalServiceFactory = ApprovalApplicationService,
    board_service_factory: BoardServiceFactory = BoardApplicationService,
    papers_service_factory: PapersServiceFactory = PapersApplicationService,
    auth_service_factory: AuthServiceFactory = AuthApplicationService,
    paper_user_state_service_factory: PaperUserStateServiceFactory = PaperUserStateApplicationService,
) -> ApiServices:
    return ApiServices(
        worker_service_factory=worker_service_factory,
        run_service_factory=run_service_factory,
        run_operation_service_factory=run_operation_service_factory,
        report_service_factory=report_service_factory,
        memory_service_factory=memory_service_factory,
        diagnostic_service_factory=diagnostic_service_factory,
        source_service_factory=source_service_factory,
        entity_service_factory=entity_service_factory,
        subscription_service_factory=subscription_service_factory,
        mcp_service_factory=mcp_service_factory,
        run_inspection_service_factory=run_inspection_service_factory,
        artifact_service_factory=artifact_service_factory,
        storage_service_factory=storage_service_factory,
        schedule_service_factory=schedule_service_factory,
        approval_service_factory=approval_service_factory,
        board_service_factory=board_service_factory,
        papers_service_factory=papers_service_factory,
        auth_service_factory=auth_service_factory,
        paper_user_state_service_factory=paper_user_state_service_factory,
    )


def get_actor_context(request: Request) -> ActorContext:
    actor = getattr(request.state, "actor_context", None)
    if isinstance(actor, ActorContext):
        return actor
    return actor_context_from_headers(request.headers, request_id="")
