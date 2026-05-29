from __future__ import annotations

from business.projects.dto import CaseSearchQuery, CaseSearchResult, PageInfo, dataset_meta
from business.projects.models import ModuleCase, ProjectDataset


class ProjectCasesService:
    def search(self, dataset: ProjectDataset, query: CaseSearchQuery) -> CaseSearchResult:
        cases = [case for case in dataset.cases if _matches_case(case, query)]
        cases.sort(key=lambda case: (_reuse_rank(case.reference_value.value), case.title), reverse=True)
        page, items = _paginate(cases, page=query.page, page_size=query.limit or query.page_size)
        return CaseSearchResult(cases=items, page=page, meta=dataset_meta(dataset))

    def get(self, dataset: ProjectDataset, case_id: str) -> ModuleCase | None:
        for case in dataset.cases:
            if case.id == case_id:
                return case
        return None


def _matches_case(case: ModuleCase, query: CaseSearchQuery) -> bool:
    haystack = " ".join(
        [
            case.title,
            case.business_domain,
            case.module_type,
            case.problem,
            case.design_summary,
            case.plain_explanation,
            case.design_logic,
            " ".join(case.suitable_for),
            " ".join(pattern.name for pattern in case.patterns),
            " ".join(component.name for component in case.components),
        ]
    ).casefold()
    if query.q and query.q.casefold() not in haystack:
        return False
    if query.business_domain and query.business_domain.casefold() != case.business_domain.casefold():
        return False
    if query.module_type and query.module_type.casefold() != case.module_type.casefold():
        return False
    if query.pattern and query.pattern.casefold() not in haystack:
        return False
    if query.migration_level and query.migration_level.casefold() != case.migration_level.value:
        return False
    if query.difficulty and query.difficulty.casefold() != case.difficulty.value:
        return False
    return True


def _reuse_rank(value: str) -> int:
    return {"high": 3, "medium": 2, "low": 1}.get(value, 0)


def _paginate(items: list[ModuleCase], *, page: int, page_size: int) -> tuple[PageInfo, list[ModuleCase]]:
    resolved_page = max(1, int(page or 1))
    resolved_page_size = max(1, min(100, int(page_size or 24)))
    start = (resolved_page - 1) * resolved_page_size
    end = start + resolved_page_size
    return (
        PageInfo(
            page=resolved_page,
            page_size=resolved_page_size,
            total=len(items),
            has_next=end < len(items),
            next_cursor=str(resolved_page + 1) if end < len(items) else None,
        ),
        items[start:end],
    )
