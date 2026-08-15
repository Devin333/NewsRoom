from __future__ import annotations

from collections.abc import Iterable

from framework.events.application import (
    EventMigrationAssessmentApplicationPort,
    GraphEventProjectionApplicationPort,
    GraphEventProjectionApplicationRequest,
    GraphEventProjectionApplicationResult,
    MigrationDryRunReport,
    MigrationSourceRecord,
)


class GraphEventPreparationApplicationService:
    """Inactive interface path over event-owned application ports only."""

    def __init__(
        self,
        *,
        projection: GraphEventProjectionApplicationPort,
        migration: EventMigrationAssessmentApplicationPort,
    ) -> None:
        if not isinstance(projection, GraphEventProjectionApplicationPort):
            raise TypeError(
                "projection must implement GraphEventProjectionApplicationPort"
            )
        if not isinstance(migration, EventMigrationAssessmentApplicationPort):
            raise TypeError(
                "migration must implement EventMigrationAssessmentApplicationPort"
            )
        self._projection = projection
        self._migration = migration

    def project_graph_history(
        self,
        request: GraphEventProjectionApplicationRequest,
    ) -> GraphEventProjectionApplicationResult:
        return self._projection.project_graph_history(request)

    def assess_event_migration(
        self,
        records: Iterable[MigrationSourceRecord],
        *,
        fail_fast: bool = False,
    ) -> MigrationDryRunReport:
        return self._migration.assess_event_migration(
            records,
            fail_fast=fail_fast,
        )


__all__ = ["GraphEventPreparationApplicationService"]
