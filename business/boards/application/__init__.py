from business.boards.application.feedback import BoardFeedbackService
from business.boards.application.improvement import BoardImprovementService
from business.boards.application.result import (
    BoardReportExtractionResult,
    BoardRunApplicationResult,
    BoardRunApplicationResultBuilder,
)


def __getattr__(name: str):
    if name == "BoardServiceRuntime":
        from business.boards.application.service_runtime import BoardServiceRuntime

        return BoardServiceRuntime
    raise AttributeError(name)

__all__ = [
    "BoardFeedbackService",
    "BoardImprovementService",
    "BoardReportExtractionResult",
    "BoardRunApplicationResult",
    "BoardRunApplicationResultBuilder",
    "BoardServiceRuntime",
]
