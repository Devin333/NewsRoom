from business.boards.project_radar.board_service import ProjectRadarBoardService


class ProjectRadarWorkflow:
    def run(self, signals, *, context=None):
        return ProjectRadarBoardService().build_board_run_result(signals, context=context)
