import { describe, expect, it } from "vitest";
import { evidences, reports, techItems, topics } from "@/lib/mock-data";
import { buildSearchIndex, searchIndex } from "@/lib/search";
import { extractToc } from "@/features/reports/components/report-toc";

describe("Task 03 intelligence data", () => {
  it("meets the Topic, Evidence, Tech, Report, and Search mock data floors", () => {
    expect(topics.length).toBeGreaterThanOrEqual(8);
    expect(topics.every((topic) => (topic.timeline?.length ?? 0) >= 3)).toBe(true);
    expect(evidences.length).toBeGreaterThanOrEqual(15);
    expect(techItems.length).toBeGreaterThanOrEqual(10);
    expect(reports.length).toBeGreaterThanOrEqual(6);
    expect(reports.some((report) => report.markdown?.trim())).toBe(true);
    expect(buildSearchIndex().length).toBeGreaterThanOrEqual(20);
  });

  it("searches and filters across object types", () => {
    const allResults = searchIndex("agent");
    const topicResults = searchIndex("agent", ["topic"]);

    expect(allResults.length).toBeGreaterThan(topicResults.length);
    expect(new Set(allResults.map((result) => result.objectType)).size).toBeGreaterThan(1);
    expect(topicResults.length).toBeGreaterThan(0);
    expect(topicResults.every((result) => result.objectType === "topic")).toBe(true);
  });

  it("extracts report table of contents through third-level headings", () => {
    const toc = extractToc("# Main\n\n## Section\n\n### Detail\n\n#### Ignored");

    expect(toc).toEqual([
      { id: "main", title: "Main", depth: 1 },
      { id: "section", title: "Section", depth: 2 },
      { id: "detail", title: "Detail", depth: 3 },
    ]);
  });
});
