from business.boards.cross_board.models import CrossBoardInsight, TechnologyJourney


def present_cross_board_insights(insights: list[CrossBoardInsight]) -> list[dict]:
    return [insight.to_dict() for insight in insights]


def present_technology_journey(journey: TechnologyJourney) -> dict:
    return journey.to_dict()
