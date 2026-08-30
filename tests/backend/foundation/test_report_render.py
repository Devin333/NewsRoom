from backend.foundation.models.report_output import FinalReport, render_markdown


def test_render_markdown_includes_sections_and_sources() -> None:
    report = FinalReport(
        title="Daily Report",
        sections=[{"title": "Summary", "content": "Important update."}],
        source_urls=["https://example.com/a"],
    )

    markdown = render_markdown(report)

    assert "# Daily Report" in markdown
    assert "## Summary" in markdown
    assert "- https://example.com/a" in markdown
