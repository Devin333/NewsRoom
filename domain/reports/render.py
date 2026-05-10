from __future__ import annotations

from domain.reports.models import FinalReport


def render_markdown(report: FinalReport) -> str:
    lines = [f"# {report.title}", ""]
    for section in report.sections:
        lines.extend([f"## {section['title']}", str(section["content"]), ""])
    if report.source_urls:
        lines.extend(["## Sources", *[f"- {url}" for url in report.source_urls], ""])
    return "\n".join(lines)
