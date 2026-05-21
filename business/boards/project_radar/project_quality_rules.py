from business.foundation import BoardCard


def project_quality_bucket(card: BoardCard) -> str:
    if card.score.value >= 0.8:
        return "top_project"
    if card.score.value >= 0.6:
        return "radar_watch"
    if card.score.value >= 0.4:
        return "community_watch"
    return "low_signal"
