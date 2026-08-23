"""Graph run operation application boundary.

The interface layer only submits an idempotent Graph operation to the
application service.  It never constructs a scheduler, executor, checkpoint,
or event-store mutation directly.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from framework.events.canonical import checksum_for
from interfaces.models.actor import ActorContext
from interfaces.services.harness_graph_service import (
    HarnessGraphApplicationService,
    HarnessGraphReplayResult,
    HarnessGraphRunOperationResult,
)


GraphServiceFactory = Callable[[ActorContext], HarnessGraphApplicationService]


@dataclass(frozen=True, slots=True)
class GraphRunOperationApplicationResult:
    operation: HarnessGraphRunOperationResult

    def to_dict(self) -> dict[str, Any]:
        return self.operation.to_dict()


class GraphRunOperationApplicationService:
    """Submit only Graph-owned operations through the Graph application service."""

    def __init__(
        self,
        graph_service_factory: GraphServiceFactory | None = None,
    ) -> None:
        self._graph_service_factory = graph_service_factory

    def cancel_run(
        self,
        run_id: str,
        *,
        reason_code: str,
        actor: ActorContext,
        cancellation_id: str | None = None,
    ) -> GraphRunOperationApplicationResult:
        service = self._service(actor)
        operation_id = cancellation_id or checksum_for(
            {
                "operation": "cancel",
                "run_id": run_id,
                "reason_code": reason_code,
                "actor_id": actor.actor_id,
            }
        )
        return GraphRunOperationApplicationResult(
            service.cancel_run(
                run_id,
                cancellation_id=operation_id,
                reason_code=reason_code,
            )
        )

    def replay_run(
        self,
        run_id: str,
        *,
        actor: ActorContext,
        through_sequence: int | None = None,
    ) -> HarnessGraphReplayResult:
        return self._service(actor).replay_run(
            run_id,
            through_sequence=through_sequence,
        )

    def _service(self, actor: ActorContext) -> HarnessGraphApplicationService:
        if not isinstance(actor, ActorContext):
            raise TypeError("actor must be ActorContext")
        if self._graph_service_factory is None:
            raise RuntimeError("Graph run operation capability is unavailable")
        service = self._graph_service_factory(actor)
        if not isinstance(service, HarnessGraphApplicationService):
            raise TypeError("graph service factory returned an invalid service")
        return service


__all__ = [
    "GraphRunOperationApplicationResult",
    "GraphRunOperationApplicationService",
]
