from __future__ import annotations

from business.evaluation.fixtures import _cases_for_board


def ai_news_eval_cases():
    return _cases_for_board("ai_news")


__all__ = ["ai_news_eval_cases"]
