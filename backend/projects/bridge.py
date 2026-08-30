from __future__ import annotations

import re
from datetime import datetime, timezone as _tz
UTC = _tz.utc
from typing import Any
from urllib.parse import urlparse

from backend.foundation import slugify
from backend.projects.enums import (
    CollectionType,
    IntegrationDifficulty,
    ProjectSourceType,
    ProjectType,
    ReuseLevel,
)
from backend.projects.models import (
    CaseComponent,
    CollectionItem,
    CollectionSection,
    DataFlowStep,
    DesignPattern,
    ModuleCase,
    Project,
    ProjectCapability,
    ProjectCollection,
    ProjectDataset,
    ProjectGrowthSnapshot,
    ProjectMetricSnapshot,
    ProjectSource,
    ProjectToolProfile,
    stable_id,
)


FORBIDDEN_METADATA_KEYS = {
    "raw_payload",
    "raw_content",
    "raw_html",
    "full_text",
    "secret",
    "api_key",
    "token",
    "authorization",
    "cookie",
}

GITHUB_RE = re.compile(r"https://github\.com/(?P<owner>[A-Za-z0-9_.-]+)/(?P<repo>[A-Za-z0-9_.-]+)", re.IGNORECASE)
CODE_WORDS = {"api", "cli", "sdk", "docker", "github", "repository", "repo", "library", "framework", "agent", "tool", "workflow"}


class ProjectRadarBridge:
    def map_payload(
        self,
        payload: Any,
        *,
        source: str = "artifact",
        source_run_id: str | None = None,
        generated_at: datetime | None = None,
    ) -> ProjectDataset:
        payload_record = _record(payload)
        cards = _extract_cards(payload)
        detail_pages = _extract_detail_pages(payload)
        resolved_generated_at = generated_at or _payload_generated_at(payload_record) or _latest_card_time(cards)
        dataset = ProjectDataset(
            source="backend" if source == "backend" else "artifact",
            source_run_id=source_run_id or _payload_run_id(payload_record),
            generated_at=resolved_generated_at,
            notices=[],
        )
        if not cards:
            dataset.notices.append("No Project Radar cards were found in the real artifact payload.")
            return dataset

        project_by_id: dict[str, Project] = {}
        for index, card in enumerate(cards):
            project = self._project_from_card(card, index=index)
            if project is None:
                continue
            project_by_id[project.id] = project
            dataset.projects.append(project)
            dataset.metric_snapshots.append(self._metric_snapshot(project, card))
            dataset.growth_snapshots.append(self._growth_snapshot(project, card))
            dataset.sources.extend(self._sources(project, card))
            capabilities = self._capabilities(project, card, detail_pages)
            dataset.capabilities.extend(capabilities)
            dataset.tool_profiles.append(self._tool_profile(project, card, capabilities))
            case = self._case(project, card, capabilities, detail_pages)
            if case is not None:
                dataset.cases.append(case)

        dataset.collections.extend(self._collections(dataset))
        if not dataset.projects:
            dataset.notices.append("Project Radar artifacts were present, but no public project entities could be mapped.")
        if not dataset.cases and dataset.projects:
            dataset.notices.append("No module cases could be derived from the current Project Radar artifact.")
        if not dataset.tool_profiles and dataset.projects:
            dataset.notices.append("No tool profiles could be derived from the current Project Radar artifact.")
        return dataset

    def _project_from_card(self, card: dict[str, Any], *, index: int) -> Project | None:
        explicit_name = _text(
            card.get("name"),
            card.get("repo_full_name"),
            _nested(card, "primary_object_ref", "label"),
            card.get("title"),
        )
        summary = _text(card.get("summary"), card.get("description"), card.get("subtitle"))
        url_candidates = _url_candidates(card)
        github_url = _first_github_url(url_candidates)
        canonical_url = github_url or _first_http_url(url_candidates)
        if canonical_url is None:
            return None
        derived_name = _name_from_url(canonical_url)
        name = explicit_name or derived_name
        if name is None:
            return None
        full_name = _repo_full_name(card, github_url=github_url, name=name)
        resolved_name = _repo_name(full_name) or name
        project_id = str(card.get("project_id") or card.get("id") or card.get("card_id") or stable_id("project", canonical_url, resolved_name))
        tags = _tags_from_card(card)
        project_type = ProjectType.TOOL if github_url or _contains_any([summary, name, *tags], CODE_WORDS) else ProjectType.PROJECT
        features = _feature_scores(card)
        confidence_value = _float(_nested(card, "confidence", "value"), default=0.5)
        metadata = _sanitize_metadata(
            {
                "card_id": card.get("card_id"),
                "repo_full_name": full_name,
                "ranking_features": card.get("ranking_features"),
                "board_specific_features": features,
                "ranking_reason": card.get("ranking_reason"),
                "metrics": card.get("metrics"),
                "subtitle": card.get("subtitle"),
            }
        )
        return Project(
            id=project_id,
            name=resolved_name,
            slug=str(card.get("slug") or slugify(full_name or resolved_name)),
            tagline=_text(card.get("tagline"), card.get("subtitle")),
            description=summary,
            canonical_url=canonical_url,
            website_url=_first_non_github_http_url(url_candidates),
            github_url=github_url,
            docs_url=_first_url_containing(url_candidates, ("docs", "documentation")),
            demo_url=_first_url_containing(url_candidates, ("demo", "example")),
            project_type=project_type,
            category=_category_from_tags(tags, summary),
            tags=tags,
            source_confidence=confidence_value,
            ai_summary=summary,
            why_it_matters=_text(card.get("why_it_matters"), card.get("ranking_reason"), summary),
            suitable_for=_suitable_for(tags, summary),
            learnable_points=_learnable_points(card, tags),
            created_at=_datetime(card.get("published_at")) or _datetime(card.get("generated_at")) or _now(),
            updated_at=_datetime(card.get("generated_at")) or _now(),
            metadata=metadata,
        )

    def _metric_snapshot(self, project: Project, card: dict[str, Any]) -> ProjectMetricSnapshot:
        features = _feature_scores(card)
        return ProjectMetricSnapshot(
            id=stable_id("metric", project.id, card.get("generated_at") or ""),
            project_id=project.id,
            snapshot_at=_datetime(card.get("generated_at")) or _now(),
            github_stars=_int(card.get("stars") or card.get("github_stars") or _metric_value(card, "Stars")),
            github_forks=_int(card.get("forks") or card.get("github_forks") or _metric_value(card, "Forks")),
            github_watchers=_int(card.get("watchers") or card.get("github_watchers")),
            github_open_issues=_int(card.get("open_issues") or card.get("github_open_issues")),
            product_hunt_votes=_int(card.get("product_hunt_votes")),
            hn_points=_int(card.get("hn_points")),
            hn_comments=_int(card.get("hn_comments")),
            source_mentions=_evidence_ref_count(card),
            quality_score=_float(_nested(card, "quality", "score", "value"), default=None)
            or _float(_nested(card, "score", "value"), default=None),
            activity_score=features.get("activity"),
            evidence_score=features.get("implementation_evidence"),
            metadata=_sanitize_metadata(
                {
                    "repo_health": features.get("repo_health"),
                    "community_adoption": features.get("community_adoption"),
                    "technology_mapping": features.get("technology_mapping"),
                    "raw_score": _nested(card, "score", "value") or card.get("score"),
                }
            ),
        )

    def _growth_snapshot(self, project: Project, card: dict[str, Any]) -> ProjectGrowthSnapshot:
        delta = _int(card.get("star_growth_7d") or card.get("starGrowth7d") or card.get("stars_delta"))
        return ProjectGrowthSnapshot(
            id=stable_id("growth", project.id, "7d", card.get("generated_at") or ""),
            project_id=project.id,
            window="7d",
            stars_delta=delta,
            votes_delta=_int(card.get("votes_delta")),
            mentions_delta=_evidence_ref_count(card),
            release_count=_int(card.get("release_count")) or 0,
            computed_at=_datetime(card.get("generated_at")) or _now(),
            metadata=_sanitize_metadata({"ranking_features": _feature_scores(card)}),
        )

    def _sources(self, project: Project, card: dict[str, Any]) -> list[ProjectSource]:
        result: list[ProjectSource] = []
        for index, source in enumerate(card.get("evidence_refs") or []):
            if not isinstance(source, dict):
                continue
            url = _text(source.get("url"), source.get("source_url"))
            if not url:
                continue
            result.append(
                ProjectSource(
                    id=stable_id("project_source", project.id, url, index),
                    project_id=project.id,
                    source_name=_text(source.get("source_name"), source.get("source_id"), "Project Radar") or "Project Radar",
                    source_type=_source_type(source.get("source_type")),
                    source_url=url,
                    external_id=_text(source.get("external_id")),
                    raw_title=_text(source.get("title")),
                    raw_description=_text(source.get("summary")),
                    raw_metadata=_sanitize_metadata({k: v for k, v in source.items() if k not in {"url", "source_url"}}),
                    fetched_at=_datetime(source.get("collected_at")) or _now(),
                )
            )
        if project.github_url and not any(source.source_url == project.github_url for source in result):
            result.append(
                ProjectSource(
                    id=stable_id("project_source", project.id, project.github_url),
                    project_id=project.id,
                    source_name="GitHub",
                    source_type=ProjectSourceType.GITHUB,
                    source_url=project.github_url,
                    fetched_at=project.updated_at,
                )
            )
        return result

    def _capabilities(
        self,
        project: Project,
        card: dict[str, Any],
        detail_pages: list[dict[str, Any]],
    ) -> list[ProjectCapability]:
        texts = [project.description or "", project.why_it_matters or "", _detail_text_for_project(project, detail_pages)]
        tags = project.tags or _tags_from_card(card)
        candidates: list[tuple[str, str, str]] = []
        if _contains_any(texts + tags, {"agent", "workflow", "automation"}):
            candidates.append(("Agent workflow", "workflow", "Plan, orchestrate, or automate multi-step AI tasks."))
        if _contains_any(texts + tags, {"rag", "retrieval", "search", "knowledge"}):
            candidates.append(("Retrieval augmentation", "retrieval", "Connect knowledge sources to model-facing answers."))
        if _contains_any(texts + tags, {"eval", "benchmark", "quality", "test"}):
            candidates.append(("Evaluation", "evaluation", "Measure outputs, quality, and regression behavior."))
        if _contains_any(texts + tags, {"code", "coding", "developer", "cli"}):
            candidates.append(("Developer automation", "developer_tool", "Assist coding, review, generation, or local developer workflows."))
        result: list[ProjectCapability] = []
        for name, capability_type, description in candidates[:4]:
            result.append(
                ProjectCapability(
                    id=stable_id("capability", project.id, name),
                    project_id=project.id,
                    name=name,
                    capability_type=capability_type,
                    description=description,
                    input_desc=_infer_input_desc(texts),
                    output_desc=_infer_output_desc(texts),
                    reusable_level=_reuse_level(project, card),
                    difficulty=_difficulty(project, card),
                    target_modules=_target_modules(tags, texts),
                )
            )
        return result

    def _tool_profile(
        self,
        project: Project,
        card: dict[str, Any],
        capabilities: list[ProjectCapability],
    ) -> ProjectToolProfile:
        text_values = [project.name, project.description or "", " ".join(project.tags)]
        return ProjectToolProfile(
            project_id=project.id,
            tool_type=_tool_type(project, capabilities),
            input_types=_input_types(text_values),
            output_types=_output_types(text_values),
            is_open_source=bool(project.github_url),
            license=_text(card.get("license"), _metric_value(card, "License")),
            local_deployable=bool(project.github_url) or _contains_any(text_values, {"local", "self-host", "docker"}),
            has_api=_contains_any(text_values, {"api", "server", "service"}),
            has_cli=_contains_any(text_values, {"cli", "terminal", "command"}),
            has_python_sdk=_contains_any(text_values, {"python", "sdk"}),
            has_docker=_contains_any(text_values, {"docker", "container"}),
            integration_difficulty=_difficulty(project, card),
            recommended_integration="wrap_as_service" if _contains_any(text_values, {"api", "service", "server"}) else "reference_only",
            target_modules=sorted({module for capability in capabilities for module in capability.target_modules}),
            setup_commands=[],
            usage_example=None,
            known_limits=[],
            experiment_status="untested",
        )

    def _case(
        self,
        project: Project,
        card: dict[str, Any],
        capabilities: list[ProjectCapability],
        detail_pages: list[dict[str, Any]],
    ) -> ModuleCase | None:
        detail_text = _detail_text_for_project(project, detail_pages)
        explicit_case = _explicit_case_record(card)
        if detail_text is None and explicit_case is None:
            return None
        case_id = stable_id("case", project.id)
        business_domain = _case_domain(project)
        module_type = _case_module_type(capabilities)
        problem = _text(_nested(explicit_case, "problem"), _nested(explicit_case, "use_case"), project.description)
        design_summary = _text(_nested(explicit_case, "design_summary"), _nested(explicit_case, "summary"), project.ai_summary, detail_text)
        design_logic = _text(_nested(explicit_case, "design_logic"), _nested(explicit_case, "logic"), project.why_it_matters, detail_text)
        input_desc = capabilities[0].input_desc if capabilities else _infer_input_desc([detail_text or "", project.description or ""])
        output_desc = capabilities[0].output_desc if capabilities else _infer_output_desc([detail_text or "", project.description or ""])
        component = CaseComponent(
            id=stable_id("component", case_id, "core"),
            case_id=case_id,
            name=f"{project.name} core module",
            component_type=module_type,
            responsibility=problem or design_summary or detail_text or project.description or project.name,
            input_desc=input_desc,
            output_desc=output_desc,
            dependency_desc=project.github_url or project.canonical_url,
            plain_explanation=detail_text or design_summary or project.description or project.name,
            migration_advice="Use the public repository or source references as evidence before adopting the design.",
        )
        pattern = DesignPattern(
            id=stable_id("pattern", case_id, module_type),
            case_id=case_id,
            name=f"{module_type.replace('_', ' ').title()} reference pattern",
            pattern_type=module_type,
            explanation=design_logic or design_summary or detail_text or project.description or project.name,
            when_to_use="Use when your module has similar input/output and operational constraints.",
            pros=[point for point in project.learnable_points[:3]],
            cons=["Requires independent evaluation before production adoption."],
        )
        return ModuleCase(
            id=case_id,
            project_id=project.id,
            title=f"{project.name} module case",
            business_domain=business_domain,
            module_type=module_type,
            problem=problem or f"Study the real Project Radar evidence for {project.name}.",
            design_summary=design_summary or "",
            plain_explanation=detail_text or design_summary or "",
            design_logic=design_logic or "",
            components=[component],
            patterns=[pattern],
            data_flow=[
                DataFlowStep(
                    id=stable_id("flow", case_id, "input"),
                    case_id=case_id,
                    order=1,
                    title="Input and context",
                    description=component.input_desc or "Project input is inferred from public Project Radar evidence.",
                ),
                DataFlowStep(
                    id=stable_id("flow", case_id, "output"),
                    case_id=case_id,
                    order=2,
                    title="Output and reuse",
                    description=component.output_desc or "Output is inferred from capabilities and source references.",
                ),
            ],
            migration_level=_reuse_level(project, card),
            reference_value=_reuse_level(project, card),
            difficulty=_difficulty(project, card),
            suitable_for=project.suitable_for,
            source_refs=[source.source_url for source in self._sources(project, card)],
        )

    def _collections(self, dataset: ProjectDataset) -> list[ProjectCollection]:
        collections: list[ProjectCollection] = []
        if not dataset.projects:
            return collections
        by_category: dict[str, list[Project]] = {}
        for project in dataset.projects:
            key = project.category or "general"
            by_category.setdefault(key, []).append(project)
        for category, projects in sorted(by_category.items()):
            collection_id = stable_id("collection", category)
            items = [
                CollectionItem(
                    id=stable_id("collection_item", collection_id, project.id),
                    collection_id=collection_id,
                    item_type="project",
                    item_id=project.id,
                    title=project.name,
                    reason=project.why_it_matters or project.description or "Real Project Radar project.",
                    order=index + 1,
                    difficulty=_difficulty(project, {}).value,
                    recommended_action="study_case" if project.id in {case.project_id for case in dataset.cases} else "inspect_sources",
                )
                for index, project in enumerate(projects[:8])
            ]
            section = CollectionSection(
                id=stable_id("collection_section", collection_id, "projects"),
                title=f"{category.replace('_', ' ').title()} projects",
                description="Projects derived from real Project Radar artifacts.",
                order=1,
                items=items,
            )
            collections.append(
                ProjectCollection(
                    id=collection_id,
                    slug=slugify(category),
                    title=f"{category.replace('_', ' ').title()} project set",
                    subtitle="Derived from Project Radar",
                    description="A curated collection generated only from real Project Radar project evidence.",
                    collection_type=CollectionType.TOPIC,
                    tags=[category],
                    target_audience=["product", "engineering"],
                    learning_goals=["Compare real project capabilities", "Identify reusable module patterns"],
                    sections=[section],
                    item_count=len(items),
                    curator_note="This collection is derived from Project Radar artifacts; no synthetic projects are added.",
                )
            )
        return collections


def _extract_cards(payload: Any) -> list[dict[str, Any]]:
    record = _record(payload)
    candidates = [
        record.get("cards"),
        _nested(record, "board_output", "cards"),
        _nested(record, "output", "cards"),
        _nested(record, "output", "board_output", "cards"),
    ]
    if isinstance(payload, list):
        candidates.insert(0, payload)
    for value in candidates:
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
    return []


def _extract_detail_pages(payload: Any) -> list[dict[str, Any]]:
    record = _record(payload)
    candidates = [
        record.get("detail_pages"),
        _nested(record, "board_output", "detail_pages"),
        _nested(record, "output", "detail_pages"),
        _nested(record, "output", "board_output", "detail_pages"),
    ]
    for value in candidates:
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
    return []


def _evidence_ref_count(card: dict[str, Any]) -> int:
    refs = card.get("evidence_refs") or []
    return len([item for item in refs if isinstance(item, dict)])


def _explicit_case_record(card: dict[str, Any]) -> dict[str, Any] | None:
    for key in ("module_case", "case", "design_case"):
        value = card.get(key)
        if isinstance(value, dict):
            return value
    return None


def _record(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _nested(record: Any, *keys: str) -> Any:
    current = record
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def _text(*values: Any) -> str | None:
    for value in values:
        if value is None:
            continue
        text = " ".join(str(value).split())
        if text:
            return text
    return None


def _int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(float(str(value).replace(",", "")))
    except (TypeError, ValueError):
        return None


def _float(value: Any, *, default: float | None = 0.0) -> float | None:
    if value is None or value == "":
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _datetime(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.astimezone(UTC) if value.tzinfo else value.replace(tzinfo=UTC)
    try:
        text = str(value).strip()
        if not text:
            return None
        return datetime.fromisoformat(text.replace("Z", "+00:00")).astimezone(UTC)
    except ValueError:
        return None


def _now() -> datetime:
    return datetime.now(UTC)


def _payload_generated_at(record: dict[str, Any]) -> datetime | None:
    return _datetime(record.get("generated_at") or _nested(record, "artifact_metadata", "generated_at") or _nested(record, "board_output", "generated_at"))


def _payload_run_id(record: dict[str, Any]) -> str | None:
    return _text(record.get("run_id"), _nested(record, "artifact_metadata", "run_id"))


def _latest_card_time(cards: list[dict[str, Any]]) -> datetime | None:
    times = [_datetime(card.get("generated_at")) for card in cards]
    values = [value for value in times if value is not None]
    return max(values) if values else None


def _url_candidates(card: dict[str, Any]) -> list[str]:
    values: list[Any] = [
        card.get("github_url"),
        card.get("githubUrl"),
        card.get("repo_url"),
        card.get("repoUrl"),
        card.get("repository_url"),
        card.get("url"),
        card.get("source_url"),
        _nested(card, "metadata", "url"),
        _nested(card, "metadata", "repo_url"),
    ]
    for ref in card.get("evidence_refs") or []:
        if isinstance(ref, dict):
            values.extend([ref.get("url"), ref.get("source_url")])
    text_values = [str(value) for value in [card.get("summary"), card.get("description"), card.get("subtitle")] if value]
    for text in text_values:
        values.extend(match.group(0) for match in GITHUB_RE.finditer(text))
    return [str(value).strip() for value in values if str(value or "").strip()]


def _first_github_url(urls: list[str]) -> str | None:
    for url in urls:
        match = GITHUB_RE.search(url)
        if match:
            return f"https://github.com/{match.group('owner')}/{match.group('repo').removesuffix('.git')}"
    return None


def _first_http_url(urls: list[str]) -> str | None:
    for url in urls:
        if url.startswith("https://") or url.startswith("http://"):
            return url
    return None


def _first_non_github_http_url(urls: list[str]) -> str | None:
    for url in urls:
        if (url.startswith("https://") or url.startswith("http://")) and "github.com" not in url.lower():
            return url
    return None


def _first_url_containing(urls: list[str], needles: tuple[str, ...]) -> str | None:
    for url in urls:
        lowered = url.lower()
        if any(needle in lowered for needle in needles):
            return url
    return None


def _repo_full_name(card: dict[str, Any], *, github_url: str | None, name: str) -> str | None:
    explicit = _text(card.get("repo_full_name"), card.get("full_name"))
    if explicit and "/" in explicit:
        return explicit
    if github_url:
        parsed = urlparse(github_url)
        parts = [part for part in parsed.path.strip("/").split("/") if part]
        if len(parts) >= 2:
            return f"{parts[0]}/{parts[1].removesuffix('.git')}"
    return name if "/" in name else None


def _repo_name(full_name: str | None) -> str | None:
    if not full_name:
        return None
    return full_name.split("/")[-1]


def _name_from_url(url: str | None) -> str | None:
    if not url:
        return None
    parsed = urlparse(url)
    parts = [part for part in parsed.path.strip("/").split("/") if part]
    if parts:
        return parts[-1].removesuffix(".git")
    if parsed.netloc:
        return parsed.netloc
    return None


def _tags_from_card(card: dict[str, Any]) -> list[str]:
    values: list[str] = []
    for key in ("tags", "topics", "categories"):
        raw = card.get(key)
        if isinstance(raw, list):
            values.extend(str(item) for item in raw)
        elif raw:
            values.append(str(raw))
    for badge in card.get("badges") or []:
        if isinstance(badge, dict) and badge.get("label"):
            values.append(str(badge["label"]))
    for ref in card.get("related_refs") or []:
        if isinstance(ref, dict) and ref.get("label"):
            values.append(str(ref["label"]))
    clean: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = value.strip().lower().replace(" ", "_")
        if text and text not in seen:
            seen.add(text)
            clean.append(text)
    return clean


def _feature_scores(card: dict[str, Any]) -> dict[str, float]:
    raw = card.get("ranking_features")
    if not isinstance(raw, dict):
        raw = _nested(card, "metadata", "board_specific_features")
    result: dict[str, float] = {}
    if isinstance(raw, dict):
        for key, value in raw.items():
            numeric = _float(value, default=None)
            if numeric is not None:
                result[str(key)] = max(0.0, min(1.0, numeric))
    for metric in card.get("metrics") or []:
        if not isinstance(metric, dict):
            continue
        label = str(metric.get("label") or "").strip().lower().replace(" ", "_")
        numeric = _float(metric.get("value"), default=None)
        if label and numeric is not None and numeric <= 1:
            result.setdefault(label, max(0.0, min(1.0, numeric)))
    return result


def _metric_value(card: dict[str, Any], label: str) -> Any:
    target = label.casefold()
    for metric in card.get("metrics") or []:
        if isinstance(metric, dict) and str(metric.get("label") or "").casefold() == target:
            return metric.get("value")
    return None


def _category_from_tags(tags: list[str], summary: str | None) -> str | None:
    haystack = " ".join([summary or "", *tags]).lower()
    mapping = {
        "agent_framework": {"agent", "workflow", "automation", "codex"},
        "rag": {"rag", "retrieval", "knowledge", "search"},
        "evaluation": {"eval", "benchmark", "quality", "test"},
        "coding": {"code", "coding", "developer", "cli"},
        "llm_infra": {"inference", "serving", "model", "llm"},
        "multimodal": {"image", "video", "audio", "vision"},
        "data": {"data", "dataset", "etl"},
        "memory": {"memory", "state", "context"},
    }
    for category, needles in mapping.items():
        if any(needle in haystack for needle in needles):
            return category
    return tags[0] if tags else None


def _source_type(value: Any) -> ProjectSourceType:
    normalized = str(value or "").strip().lower()
    mapping = {
        "github": ProjectSourceType.GITHUB,
        "official_blog": ProjectSourceType.OFFICIAL_BLOG,
        "blog": ProjectSourceType.OFFICIAL_BLOG,
        "community": ProjectSourceType.COMMUNITY,
        "paper": ProjectSourceType.PAPER,
        "rss": ProjectSourceType.RSS,
        "api": ProjectSourceType.API,
        "web": ProjectSourceType.WEB,
    }
    return mapping.get(normalized, ProjectSourceType.MANUAL)


def _contains_any(values: list[str | None], needles: set[str]) -> bool:
    haystack = " ".join(value or "" for value in values).lower()
    return any(needle in haystack for needle in needles)


def _suitable_for(tags: list[str], summary: str | None) -> list[str]:
    suitable = []
    text = " ".join([summary or "", *tags]).lower()
    if "agent" in text:
        suitable.append("agent_product")
    if "code" in text or "developer" in text:
        suitable.append("developer_tooling")
    if "health" in text:
        suitable.append("industry_workflow")
    if not suitable:
        suitable.append("module_reference")
    return suitable


def _learnable_points(card: dict[str, Any], tags: list[str]) -> list[str]:
    points = []
    features = _feature_scores(card)
    for key, value in sorted(features.items(), key=lambda item: item[1], reverse=True):
        if value > 0:
            points.append(f"{key.replace('_', ' ').title()} signal {value:.2f}")
    points.extend(tag.replace("_", " ").title() for tag in tags[:3])
    return points[:5]


def _reuse_level(project: Project, card: dict[str, Any]) -> ReuseLevel:
    features = _feature_scores(card)
    score = max(features.get("implementation_evidence", 0), features.get("repo_health", 0), project.source_confidence)
    if score >= 0.7:
        return ReuseLevel.HIGH
    if score >= 0.4:
        return ReuseLevel.MEDIUM
    return ReuseLevel.LOW


def _difficulty(project: Project, card: dict[str, Any]) -> IntegrationDifficulty:
    text = " ".join([project.description or "", " ".join(project.tags)]).lower()
    if "enterprise" in text or "platform" in text:
        return IntegrationDifficulty.HIGH
    if project.github_url or "api" in text or "cli" in text:
        return IntegrationDifficulty.MEDIUM
    return IntegrationDifficulty.LOW


def _target_modules(tags: list[str], texts: list[str]) -> list[str]:
    text = " ".join(str(value) for value in [*tags, *texts] if value).lower()
    modules = []
    if "agent" in text:
        modules.append("agent_orchestration")
    if "rag" in text or "search" in text:
        modules.append("knowledge_retrieval")
    if "code" in text or "developer" in text:
        modules.append("developer_workflow")
    if "eval" in text or "quality" in text:
        modules.append("quality_evaluation")
    return modules or ["product_reference"]


def _infer_input_desc(texts: list[str]) -> str:
    if _contains_any(texts, {"repo", "code", "developer"}):
        return "Repository, task, or code context."
    if _contains_any(texts, {"document", "knowledge", "rag"}):
        return "Documents, queries, or knowledge sources."
    return "Product requirement, user task, or source evidence."


def _infer_output_desc(texts: list[str]) -> str:
    if _contains_any(texts, {"code", "review"}):
        return "Code changes, review feedback, or developer guidance."
    if _contains_any(texts, {"answer", "search", "retrieval"}):
        return "Grounded answers, citations, or retrieved context."
    return "Reusable design guidance or operational insight."


def _tool_type(project: Project, capabilities: list[ProjectCapability]) -> str:
    if capabilities:
        return capabilities[0].capability_type
    return project.category or project.project_type.value


def _input_types(text_values: list[str]) -> list[str]:
    values = ["text"]
    if _contains_any(text_values, {"code", "repo", "github"}):
        values.append("repository")
    if _contains_any(text_values, {"document", "rag", "knowledge"}):
        values.append("documents")
    return values


def _output_types(text_values: list[str]) -> list[str]:
    values = ["analysis"]
    if _contains_any(text_values, {"code", "coding"}):
        values.append("code")
    if _contains_any(text_values, {"report", "summary"}):
        values.append("report")
    return values


def _case_domain(project: Project) -> str:
    text = " ".join([project.description or "", " ".join(project.tags)]).lower()
    if "health" in text:
        return "healthcare"
    if "education" in text:
        return "education"
    if "finance" in text or "ramp" in text:
        return "finance"
    if "code" in text or "developer" in text:
        return "developer_productivity"
    return project.category or "product_engineering"


def _case_module_type(capabilities: list[ProjectCapability]) -> str:
    if capabilities:
        return capabilities[0].capability_type
    return "reference_module"


def _detail_text_for_project(project: Project, detail_pages: list[dict[str, Any]]) -> str | None:
    for page in detail_pages:
        ref_label = _text(_nested(page, "primary_object_ref", "label"), page.get("title"))
        if ref_label and ref_label.casefold() not in {project.name.casefold(), project.slug.casefold()}:
            continue
        for section in page.get("sections") or []:
            if isinstance(section, dict) and section.get("content"):
                return _text(section.get("content"))
        return _text(page.get("summary"))
    return None


def _sanitize_metadata(value: Any) -> Any:
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for key, item in value.items():
            key_text = str(key)
            if _is_sensitive_metadata_key(key_text):
                continue
            result[key_text] = _sanitize_metadata(item)
        return result
    if isinstance(value, list):
        return [_sanitize_metadata(item) for item in value]
    return value


def _is_sensitive_metadata_key(key: str) -> bool:
    normalized = "".join(ch for ch in key.casefold() if ch.isalnum())
    exact = {"rawpayload", "rawcontent", "rawhtml", "fulltext", "authorization", "cookie", "setcookie"}
    fragments = ("secret", "token", "apikey", "credential", "password", "passwd", "sessionid")
    return normalized in exact or normalized in {"".join(ch for ch in item if ch.isalnum()) for item in FORBIDDEN_METADATA_KEYS} or any(
        fragment in normalized for fragment in fragments
    )
