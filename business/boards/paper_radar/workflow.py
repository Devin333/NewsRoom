from business.boards.paper_radar.board_service import PaperRadarBoardService


class PaperRadarWorkflow:
    def run(self, signals, *, context=None):
        return PaperRadarBoardService().build_board_run_result(signals, context=context)
