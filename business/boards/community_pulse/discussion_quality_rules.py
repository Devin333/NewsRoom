from business.foundation import BoardCard


def discussion_quality_score(card: BoardCard) -> float:
    return card.score.value
