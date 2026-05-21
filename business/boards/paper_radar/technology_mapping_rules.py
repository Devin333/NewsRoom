from business.foundation import BoardCard


def has_technology_mapping(card: BoardCard) -> bool:
    return any(ref.object_type.value == "technology" for ref in card.related_refs)
