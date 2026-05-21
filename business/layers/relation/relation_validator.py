from __future__ import annotations

from business.layers.relation.pipeline import RejectedRelation, RelationCandidate, RelationPipeline


class RelationValidator:
    def validate(self, candidate: RelationCandidate) -> RejectedRelation | None:
        return RelationPipeline()._validate(candidate)
