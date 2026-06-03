from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from business.foundation import AnalysisContext, BoardDefinition, BoardRunResult, Signal


class ProductizedSignalSelectionPort(Protocol):
    def select_signals(self, signals: list[Any], *, context: AnalysisContext) -> list[Signal]:
        ...


class ProductizedBoardRunResultPort(Protocol):
    def build_board_run_result(
        self,
        signals: list[Any],
        *,
        context: AnalysisContext | None = None,
    ) -> BoardRunResult:
        ...


class ProductizedBoardServicePort(
    ProductizedSignalSelectionPort,
    ProductizedBoardRunResultPort,
    Protocol,
):
    @property
    def board_definition(self) -> BoardDefinition:
        ...


@dataclass(frozen=True)
class ProductizedBoardPorts:
    selector: ProductizedSignalSelectionPort
    run_result_builder: ProductizedBoardRunResultPort
    board_name: str


def productized_board_ports_from_service(board_service: ProductizedBoardServicePort) -> ProductizedBoardPorts:
    return ProductizedBoardPorts(
        selector=board_service,
        run_result_builder=board_service,
        board_name=board_service.board_definition.name,
    )


__all__ = [
    "ProductizedBoardPorts",
    "ProductizedBoardRunResultPort",
    "ProductizedBoardServicePort",
    "ProductizedSignalSelectionPort",
    "productized_board_ports_from_service",
]
