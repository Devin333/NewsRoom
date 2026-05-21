from __future__ import annotations

from business.boards._intelligence import BoardScoringProfile, scoring_recipe_from_board_profile
from business.boards.ai_news.ranking_rules import AI_NEWS_PROFILE
from business.boards.community_pulse.ranking_rules import COMMUNITY_PULSE_PROFILE
from business.boards.paper_radar.ranking_rules import PAPER_RADAR_PROFILE
from business.boards.project_radar.ranking_rules import PROJECT_RADAR_PROFILE
from framework.scoring import ScoringRecipe


def board_scoring_recipe(profile: BoardScoringProfile) -> ScoringRecipe:
    return scoring_recipe_from_board_profile(profile)


def ai_news_scoring_recipe() -> ScoringRecipe:
    return board_scoring_recipe(AI_NEWS_PROFILE)


def project_radar_scoring_recipe() -> ScoringRecipe:
    return board_scoring_recipe(PROJECT_RADAR_PROFILE)


def paper_radar_scoring_recipe() -> ScoringRecipe:
    return board_scoring_recipe(PAPER_RADAR_PROFILE)


def community_pulse_scoring_recipe() -> ScoringRecipe:
    return board_scoring_recipe(COMMUNITY_PULSE_PROFILE)


def cross_board_path_scoring_recipe() -> ScoringRecipe:
    return ScoringRecipe(
        recipe_id="cross_board_path_scoring_v1",
        version="1.0",
        target_type="cross_board_path",
        gates=["block_contradiction", "duplicate_penalty", "required_stages_complete"],
        scorers=["graph_path_score"],
        rankers=["priority"],
        calibrators=["noop"],
        explainer="template",
        weights={
            "stage_completeness": 0.35,
            "board_support": 0.25,
            "evidence_chain_confidence": 0.25,
            "evidence_diversity": 0.15,
        },
        channels={
            "coverage": ["stage_completeness", "board_support"],
            "evidence": ["evidence_chain_confidence", "evidence_diversity"],
        },
        params={
            "gate_specs": {
                "required_stages_complete": {
                    "action": "block",
                    "feature": "missing_stage_count",
                    "operator": "eq",
                    "threshold": 0.0,
                    "severity": "error",
                    "reason": "required cross-board stages are missing",
                }
            }
        },
        metadata={"board_type": "cross_board", "source": "business_scoring_recipe"},
    )
