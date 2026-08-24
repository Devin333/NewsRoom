from __future__ import annotations

from fastapi import FastAPI

from interfaces.api.deps import ApiRouteHelpers, ApiServices
from interfaces.api.routers import (
    auth,
    entities,
    events,
    health,
    harness_graph,
    harness_waits,
    mcp,
    memory,
    projects,
    research,
    reports,
    runs,
    schedules,
    sources,
    storage,
    subscriptions,
    workers,
)


def include_routers(api: FastAPI, *, services: ApiServices, helpers: ApiRouteHelpers) -> None:
    for router in (
        health.create_router(services, helpers),
        auth.create_router(services, helpers),
        runs.create_router(services, helpers),
        workers.create_router(services, helpers),
        reports.create_router(services, helpers),
        research.create_router(services, helpers),
        projects.create_router(services, helpers),
        events.create_router(services, helpers),
        memory.create_router(services, helpers),
        storage.create_router(services, helpers),
        sources.create_router(services, helpers),
        entities.create_router(services, helpers),
        subscriptions.create_router(services, helpers),
        mcp.create_router(services, helpers),
        schedules.create_router(services, helpers),
        harness_graph.create_router(services, helpers),
        harness_waits.create_router(services, helpers),
    ):
        api.include_router(router)
