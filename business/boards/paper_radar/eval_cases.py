from __future__ import annotations

from business.evaluation.fixtures import _cases_for_board


def paper_radar_eval_cases():
    return _cases_for_board("paper_radar")


__all__ = ["paper_radar_eval_cases"]
