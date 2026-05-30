from __future__ import annotations

from datetime import datetime, timezone as _tz
UTC = _tz.utc

from business.foundation import slugify
from business.projects.dto import (
    CollectionCreateRequest,
    CollectionGenerateRequest,
    CollectionItemCreateRequest,
    CollectionSearchResult,
    dataset_meta,
)
from business.projects.models import CollectionItem, CollectionSection, ProjectCollection, ProjectDataset, stable_id


class ProjectCollectionsService:
    def list(
        self,
        dataset: ProjectDataset,
        user_collections: list[ProjectCollection] | None = None,
    ) -> CollectionSearchResult:
        collections = _merged_collections(dataset.collections, user_collections or [])
        collections = sorted(collections, key=lambda item: (item.status != "published", item.title))
        return CollectionSearchResult(collections=collections, meta=dataset_meta(dataset))

    def get(
        self,
        dataset: ProjectDataset,
        slug: str,
        user_collections: list[ProjectCollection] | None = None,
    ) -> ProjectCollection | None:
        for collection in _merged_collections(dataset.collections, user_collections or []):
            if collection.slug == slug or collection.id == slug:
                return collection
        return None

    def create(
        self,
        dataset: ProjectDataset,
        user_collections: list[ProjectCollection],
        request: CollectionCreateRequest,
    ) -> ProjectCollection:
        title = request.title.strip()
        description = request.description.strip()
        if not title:
            raise ValueError("collection title is required")
        if not description:
            raise ValueError("collection description is required")
        slug = _unique_slug(slugify(title), _merged_collections(dataset.collections, user_collections))
        return ProjectCollection(
            id=stable_id("project_collection", slug, request.created_by or "anonymous"),
            slug=slug,
            title=title,
            description=description,
            collection_type=request.collection_type,
            tags=_unique_texts(request.tags),
            target_audience=_unique_texts(request.target_audience),
            learning_goals=_unique_texts(request.learning_goals),
            sections=[],
            item_count=0,
            curator_note="Created by Projects module from user-provided collection metadata.",
            created_by=request.created_by,
            updated_at=_now(),
        )

    def add_item(
        self,
        dataset: ProjectDataset,
        user_collections: list[ProjectCollection],
        collection_id: str,
        request: CollectionItemCreateRequest,
    ) -> ProjectCollection | None:
        collections = list(user_collections)
        updated: ProjectCollection | None = None
        for index, collection in enumerate(collections):
            if collection.id != collection_id and collection.slug != collection_id:
                continue
            item = _collection_item(dataset, collection, request)
            sections = list(collection.sections)
            if sections:
                section = sections[0]
                sections[0] = section.model_copy(update={"items": [*section.items, item]})
            else:
                sections = [
                    CollectionSection(
                        id=stable_id("collection_section", collection.id, "items"),
                        title="Selected items",
                        description="Items explicitly added to this Projects collection.",
                        order=1,
                        items=[item],
                    )
                ]
            updated = collection.model_copy(
                update={
                    "sections": sections,
                    "item_count": sum(len(section.items) for section in sections),
                    "updated_at": _now(),
                }
            )
            collections[index] = updated
            break
        return updated

    def generate(
        self,
        dataset: ProjectDataset,
        user_collections: list[ProjectCollection],
        request: CollectionGenerateRequest,
    ) -> ProjectCollection:
        topic = request.topic.strip()
        if not topic:
            raise ValueError("collection topic is required")
        selected_projects = [
            project
            for project in dataset.projects
            if (not request.project_ids or project.id in request.project_ids)
            and _matches_topic(topic, [project.name, project.tagline, project.description, project.category, *project.tags])
        ]
        selected_cases = [
            case
            for case in dataset.cases
            if (not request.case_ids or case.id in request.case_ids)
            and _matches_topic(topic, [case.title, case.problem, case.design_summary, case.module_type, case.business_domain])
        ]
        if request.project_ids:
            selected_projects = [project for project in dataset.projects if project.id in request.project_ids]
        if request.case_ids:
            selected_cases = [case for case in dataset.cases if case.id in request.case_ids]
        if not selected_projects and not selected_cases:
            raise ValueError("no matching real Project Radar projects or cases were found")
        slug = _unique_slug(slugify(topic), _merged_collections(dataset.collections, user_collections))
        collection_id = stable_id("project_collection", "generated", slug, request.created_by or "anonymous")
        project_items = [
            CollectionItem(
                id=stable_id("collection_item", collection_id, "project", project.id),
                collection_id=collection_id,
                item_type="project",
                item_id=project.id,
                title=project.name,
                reason=project.why_it_matters or project.ai_summary or project.tagline or "Project matched the requested topic.",
                order=index + 1,
                recommended_action="Open project detail and verify source evidence.",
            )
            for index, project in enumerate(selected_projects[:12])
        ]
        case_items = [
            CollectionItem(
                id=stable_id("collection_item", collection_id, "case", case.id),
                collection_id=collection_id,
                item_type="case",
                item_id=case.id,
                title=case.title,
                reason=case.design_summary,
                order=index + 1,
                difficulty=case.difficulty.value,
                recommended_action="Review case components before migration.",
            )
            for index, case in enumerate(selected_cases[:12])
        ]
        sections: list[CollectionSection] = []
        if project_items:
            sections.append(
                CollectionSection(
                    id=stable_id("collection_section", collection_id, "projects"),
                    title="Projects",
                    description="Real Project Radar projects matched to the requested topic.",
                    order=1,
                    items=project_items,
                )
            )
        if case_items:
            sections.append(
                CollectionSection(
                    id=stable_id("collection_section", collection_id, "cases"),
                    title="Cases",
                    description="Real-derived module cases matched to the requested topic.",
                    order=2,
                    items=case_items,
                )
            )
        return ProjectCollection(
            id=collection_id,
            slug=slug,
            title=topic.title(),
            description=f"Curated Projects collection generated from real Project Radar matches for {topic}.",
            collection_type=request.collection_type,
            tags=_unique_texts([topic, *[project.category or "" for project in selected_projects]]),
            sections=sections,
            item_count=sum(len(section.items) for section in sections),
            curator_note="Generated from existing Project Radar project and case records only.",
            created_by=request.created_by,
            updated_at=_now(),
        )


def _collection_item(dataset: ProjectDataset, collection: ProjectCollection, request: CollectionItemCreateRequest) -> CollectionItem:
    if request.item_type == "external_link" and not request.external_url:
        raise ValueError("external_url is required for external_link collection items")
    if request.item_type in {"project", "tool"} and not any(project.id == request.item_id for project in dataset.projects):
        raise ValueError(f"project not found: {request.item_id}")
    if request.item_type == "case" and not any(case.id == request.item_id for case in dataset.cases):
        raise ValueError(f"case not found: {request.item_id}")
    order = request.order or (sum(len(section.items) for section in collection.sections) + 1)
    return CollectionItem(
        id=stable_id("collection_item", collection.id, request.item_type, request.item_id or request.external_url or request.title, order),
        collection_id=collection.id,
        item_type=request.item_type,
        item_id=request.item_id,
        external_url=request.external_url,
        title=request.title.strip(),
        reason=request.reason.strip(),
        order=order,
        difficulty=request.difficulty,
        recommended_action=request.recommended_action,
    )


def _merged_collections(
    artifact_collections: list[ProjectCollection],
    user_collections: list[ProjectCollection],
) -> list[ProjectCollection]:
    by_id = {collection.id: collection for collection in artifact_collections}
    for collection in user_collections:
        by_id[collection.id] = collection
    return list(by_id.values())


def _unique_slug(base: str, existing: list[ProjectCollection]) -> str:
    candidate = base or "projects-collection"
    existing_slugs = {collection.slug for collection in existing}
    if candidate not in existing_slugs:
        return candidate
    index = 2
    while f"{candidate}-{index}" in existing_slugs:
        index += 1
    return f"{candidate}-{index}"


def _matches_topic(topic: str, values: list[str | None]) -> bool:
    tokens = {token for token in topic.casefold().split() if len(token) > 2}
    if not tokens:
        return False
    haystack = " ".join(value or "" for value in values).casefold()
    return any(token in haystack for token in tokens)


def _unique_texts(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        text = str(value or "").strip()
        key = text.casefold()
        if text and key not in seen:
            seen.add(key)
            result.append(text)
    return result


def _now() -> datetime:
    return datetime.now(UTC)
