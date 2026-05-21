from business.boards.community_pulse.board_service import CommunityPulseBoardService


class CommunityPulseWorkflow:
    def run(self, signals, *, context=None):
        return CommunityPulseBoardService().build_board_run_result(signals, context=context)
