from __future__ import annotations

from business.projects.dto import CollectionSearchResult, dataset_meta
from business.projects.models import ProjectCollection, ProjectDataset


class ProjectCollectionsService:
    def list(self, dataset: ProjectDataset) -> CollectionSearchResult:
        collections = sorted(dataset.collections, key=lambda item: (item.status != "published", item.title))
        return CollectionSearchResult(collections=collections, meta=dataset_meta(dataset))

    def get(self, dataset: ProjectDataset, slug: str) -> ProjectCollection | None:
        for collection in dataset.collections:
            if collection.slug == slug or collection.id == slug:
                return collection
        return None
