from business.layers.relation.pipeline import RelationPipeline


class MentionLinker:
    def link(self, signals, extraction_results):
        return [candidate for candidate in RelationPipeline()._build_candidates(signals, extraction_results) if candidate.relation_type.value in {"mentions", "same_topic"}]
