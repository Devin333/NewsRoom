from __future__ import annotations

from typing import Literal

SectionRole = Literal["background", "related_work", "method", "experiment", "analysis", "conclusion"]

# Ordered by specificity: first match wins per role, capped at 2 roles per section
_ROLE_KEYWORDS: list[tuple[SectionRole, list[str]]] = [
    ("conclusion",    ["conclusion", "summary", "concluding", "结论", "总结"]),
    ("experiment",    ["experiment", "evaluation", "benchmark", "result", "ablation", "实验", "评估", "结果"]),
    ("analysis",      ["analysis", "discussion", "ablation study", "分析", "讨论"]),
    ("method",        ["method", "approach", "model", "architecture", "framework", "proposed", "方法", "模型", "架构"]),
    ("related_work",  ["related work", "prior work", "literature", "相关工作"]),
    ("background",    ["introduction", "problem", "motivation", "background", "overview", "引言", "介绍", "概述", "背景"]),
]


def classify_section_role(title: str, snippet: str = "") -> list[SectionRole]:
    """Classify section role from title + opening snippet. Returns up to 2 roles."""
    combined = (title + " " + snippet).lower()
    roles: list[SectionRole] = []
    for role, keywords in _ROLE_KEYWORDS:
        if any(kw in combined for kw in keywords):
            roles.append(role)
            if len(roles) == 2:
                break
    return roles


def is_abstract_section(title: str) -> bool:
    return title.strip().lower() in ("abstract", "摘要", "summary")


# Non-content sections that pollute retrieval (acknowledgments, funding, refs, etc.)
_BOILERPLATE_KEYWORDS: tuple[str, ...] = (
    "acknowledg",          # acknowledgment / acknowledgement / acknowledgments
    "funding",
    "author contribution",
    "conflict of interest",
    "declaration",
    "ethics statement",
    "reproducibility statement",
    "references",
    "bibliography",
    "appendix",            # appendices are supplementary, excluded from core retrieval
    "supplementary",
    "broader impact",
    "致谢", "参考文献", "附录",
)


def is_boilerplate_section(title: str) -> bool:
    """True for non-content sections (acknowledgments/funding/refs/appendix/...)."""
    normalized = title.strip().lower()
    return any(keyword in normalized for keyword in _BOILERPLATE_KEYWORDS)


__all__ = [
    "SectionRole",
    "classify_section_role",
    "is_abstract_section",
    "is_boilerplate_section",
]
