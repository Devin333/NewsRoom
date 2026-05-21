from __future__ import annotations

from pydantic import Field

from business.foundation import AnalysisContext, ObjectRef, PrimitiveModel
from business.layers.extraction.models import TaxonomyAssignment


class TaxonomyClassifyInput(PrimitiveModel):
    object_ref: ObjectRef
    text: str
    candidate_labels: list[str] = Field(default_factory=list)
    context: AnalysisContext


class TaxonomyClassifyOutput(PrimitiveModel):
    assignments: list[TaxonomyAssignment] = Field(default_factory=list)


class TaxonomyClassifier:
    def classify(self, input: TaxonomyClassifyInput) -> TaxonomyClassifyOutput:
        return TaxonomyClassifyOutput(assignments=[])
