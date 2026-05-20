from __future__ import annotations

from fastapi import FastAPI

from interfaces.api.deps import ApiRouteHelpers, ApiServices
from interfaces.api.routers import (
    approvals,
    boards,
    entities,
    health,
    mcp,
    memory,
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
        runs.create_router(services, helpers),
        workers.create_router(services, helpers),
        reports.create_router(services, helpers),
        boards.create_router(services, helpers),
        memory.create_router(services, helpers),
        storage.create_router(services, helpers),
        sources.create_router(services, helpers),
        entities.create_router(services, helpers),
        subscriptions.create_router(services, helpers),
        mcp.create_router(services, helpers),
        schedules.create_router(services, helpers),
        approvals.create_router(services, helpers),
    ):
        api.include_router(router)
