from __future__ import annotations

from framework.events.application import (
    GraphEventHistoryDiagnostic,
    GraphEventHistoryDiagnosticCode,
    GraphEventProjectionApplicationRequest,
    GraphEventProjectionApplicationResult,
    GraphEventProjectionApplicationStatus,
)
from framework.events.migration import MigrationDryRunReport
from framework.events.projection import GraphRunIdentity
from interfaces.services.graph_event_preparation_service import (
    GraphEventPreparationApplicationService,
)


def test_interface_service_delegates_only_to_event_application_ports(tmp_path) -> None:
    request = GraphEventProjectionApplicationRequest(
        graph_identity=_identity(),
        target=tmp_path / "events.graph.jsonl",
        tenant_id="tenant-a",
    )
    expected_projection = GraphEventProjectionApplicationResult(
        request=request,
        status=GraphEventProjectionApplicationStatus.HISTORY_ONLY,
        diagnostic=GraphEventHistoryDiagnostic(
            graph_identity=request.graph_identity,
            tenant_id=request.tenant_id,
            high_watermark=None,
            code=GraphEventHistoryDiagnosticCode.EMPTY_HISTORY,
        ),
    )
    expected_migration = MigrationDryRunReport(findings=())
    projection = _ProjectionPort(expected_projection)
    migration = _MigrationPort(expected_migration)
    service = GraphEventPreparationApplicationService(
        projection=projection,
        migration=migration,
    )

    actual_projection = service.project_graph_history(request)
    actual_migration = service.assess_event_migration((), fail_fast=True)

    assert actual_projection is expected_projection
    assert actual_migration is expected_migration
    assert projection.requests == [request]
    assert migration.calls == [((), True)]


class _ProjectionPort:
    def __init__(self, result: GraphEventProjectionApplicationResult) -> None:
        self.result = result
        self.requests = []

    def project_graph_history(
        self,
        request: GraphEventProjectionApplicationRequest,
    ) -> GraphEventProjectionApplicationResult:
        self.requests.append(request)
        return self.result


class _MigrationPort:
    def __init__(self, report: MigrationDryRunReport) -> None:
        self.report = report
        self.calls = []

    def assess_event_migration(self, records, *, fail_fast=False):
        captured = tuple(records)
        self.calls.append((captured, fail_fast))
        return self.report


def _identity() -> GraphRunIdentity:
    return GraphRunIdentity(
        run_id="run-interface-graph-event",
        graph_id="research.paper-analysis",
        graph_version="1",
        graph_schema_version="newsroom.normalized-harness-graph/v3",
        compiler_version="3",
        normalized_graph_checksum="sha256:" + "a" * 64,
    )
