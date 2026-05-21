from business.boards.ai_news.board_service import AINewsBoardService


class AINewsWorkflow:
    def run(self, signals, *, context=None):
        return AINewsBoardService().build_board_run_result(signals, context=context)
