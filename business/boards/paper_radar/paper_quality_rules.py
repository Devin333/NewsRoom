from business.foundation import BoardCard


def paper_bucket(card: BoardCard) -> str:
    if card.score.value >= 0.8:
        return "must_read"
    if card.score.value >= 0.6:
        return "radar_watch"
    if card.score.value >= 0.4:
        return "method_note"
    return "low_signal"
