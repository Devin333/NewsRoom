from __future__ import annotations

from business.memory.models import BusinessMemoryContext
from framework.scoring import FeatureVector


def build_memory_feature_vector(context: BusinessMemoryContext) -> FeatureVector:
    return context.to_feature_vector()


def merge_memory_features(base: FeatureVector, memory_context: BusinessMemoryContext) -> FeatureVector:
    return base.merge(build_memory_feature_vector(memory_context))
