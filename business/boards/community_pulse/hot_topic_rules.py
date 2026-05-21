from business.foundation import BoardCard


def pulse_bucket(card: BoardCard) -> str:
    if card.score.value >= 0.75:
        return "strong_signal"
    if card.score.value >= 0.6:
        return "controversy"
    if card.score.value >= 0.4:
        return "adoption_feedback"
    return "noise_watch"
