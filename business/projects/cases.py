from __future__ import annotations

from business.projects.dto import (
    CaseExplainRequest,
    CaseExplainResult,
    CaseMapRequest,
    CaseMapResult,
    CaseSearchQuery,
    CaseSearchResult,
    PageInfo,
    dataset_meta,
)
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

    def explain(self, dataset: ProjectDataset, case_id: str, request: CaseExplainRequest) -> CaseExplainResult | None:
        case = self.get(dataset, case_id)
        if case is None:
            return None
        project = next((item for item in dataset.projects if item.id == case.project_id), None)
        key_points = [
            case.problem,
            case.design_summary,
            case.design_logic,
            *[pattern.when_to_use for pattern in case.patterns[:3]],
        ]
        component_explanations = [
            {
                "id": component.id,
                "name": component.name,
                "responsibility": component.responsibility,
                "plain_explanation": component.plain_explanation,
                "migration_advice": component.migration_advice,
            }
            for component in case.components
        ]
        pattern_explanations = [
            {
                "id": pattern.id,
                "name": pattern.name,
                "pattern_type": pattern.pattern_type,
                "explanation": pattern.explanation,
                "when_to_use": pattern.when_to_use,
                "pros": pattern.pros,
                "cons": pattern.cons,
            }
            for pattern in case.patterns
        ]
        context_note = (
            f"User context: {request.user_context.strip()}"
            if request.user_context and request.user_context.strip()
            else "No user context was provided; explanation stays tied to the source case."
        )
        return CaseExplainResult(
            case_id=case.id,
            style=request.style,
            summary=_case_summary(case, request.style, project_name=project.name if project else None),
            key_points=_unique_lines(key_points),
            component_explanations=component_explanations,
            pattern_explanations=pattern_explanations,
            migration_notes=[
                context_note,
                f"Reuse level: {case.migration_level.value}; difficulty: {case.difficulty.value}.",
                "Keep source evidence attached before translating this case into implementation tasks.",
            ],
            source_refs=case.source_refs,
        )

    def map_to_context(self, dataset: ProjectDataset, case_id: str, request: CaseMapRequest) -> CaseMapResult | None:
        case = self.get(dataset, case_id)
        if case is None:
            return None
        context = " ".join([request.user_context, request.target_module or "", " ".join(request.constraints)]).casefold()
        reusable_components = []
        for component in case.components:
            component_text = " ".join(
                [
                    component.name,
                    component.component_type,
                    component.responsibility,
                    component.migration_advice or "",
                ]
            ).casefold()
            reusable_components.append(
                {
                    "id": component.id,
                    "name": component.name,
                    "match_reason": "Direct text overlap with user context."
                    if _token_overlap(context, component_text) > 0
                    else "Reusable as a reference pattern from the source case.",
                    "migration_advice": component.migration_advice or component.plain_explanation,
                }
            )
        fit_score = _case_context_score(case, context)
        return CaseMapResult(
            case_id=case.id,
            fit_score=fit_score,
            reusable_components=reusable_components,
            migration_steps=[
                f"Anchor the target module around the case problem: {case.problem}",
                "Select only components whose inputs and outputs match the target boundary.",
                "Carry over the design pattern intent, then re-check constraints against local runtime requirements.",
                "Attach source references and acceptance checks before implementation.",
            ],
            cautions=[
                *[f"Constraint to verify: {constraint}" for constraint in request.constraints],
                "Do not copy implementation details that are not supported by Project Radar evidence.",
            ],
            source_refs=case.source_refs,
        )


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


def _case_summary(case: ModuleCase, style: str, *, project_name: str | None = None) -> str:
    prefix = f"{project_name}: " if project_name else ""
    if style == "technical":
        return f"{prefix}{case.title} uses {len(case.components)} components and {len(case.patterns)} patterns to solve {case.problem}"
    if style == "migration":
        return f"{prefix}{case.title} is reusable at {case.migration_level.value} level for {case.module_type} work: {case.design_summary}"
    return f"{prefix}{case.plain_explanation or case.design_summary}"


def _case_context_score(case: ModuleCase, context: str) -> float:
    haystack = " ".join(
        [
            case.title,
            case.business_domain,
            case.module_type,
            case.problem,
            case.design_summary,
            " ".join(case.suitable_for),
            " ".join(pattern.name for pattern in case.patterns),
        ]
    ).casefold()
    base = _token_overlap(context, haystack)
    reuse_bonus = {"high": 0.25, "medium": 0.15, "low": 0.05}.get(case.migration_level.value, 0.0)
    return round(min(1.0, base + reuse_bonus), 4)


def _token_overlap(left: str, right: str) -> float:
    tokens = {token for token in left.split() if len(token) > 2}
    if not tokens:
        return 0.0
    return sum(1 for token in tokens if token in right) / len(tokens)


def _unique_lines(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        text = str(value or "").strip()
        key = text.casefold()
        if text and key not in seen:
            seen.add(key)
            result.append(text)
    return result


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
