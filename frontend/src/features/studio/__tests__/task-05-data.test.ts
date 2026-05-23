import { describe, expect, it } from "vitest";
import { filterMemoryItems } from "@/features/memory/hooks/use-memory-search";
import { filterQualityResults } from "@/features/quality/hooks/use-quality-results";
import { filterSources } from "@/features/sources/hooks/use-sources";
import { artifactTypeCounts, filterArtifacts } from "@/features/studio/artifacts/hooks/use-artifacts";
import { artifacts, memoryItems, qualityResults, sources } from "@/lib/mock-data";
import type { ArtifactFilters } from "@/types/artifact";
import type { MemoryFilters } from "@/types/memory";
import type { QualityFilters, QualityCheck } from "@/types/quality";
import type { SourceFilters } from "@/types/source";

const allSourceFilters: SourceFilters = {
  keyword: "",
  type: "all",
  healthStatus: "all",
  enabled: "all",
};

const allQualityFilters: QualityFilters = {
  keyword: "",
  objectType: "all",
  status: "all",
  minScore: 0,
  review: "all",
};

const allArtifactFilters: ArtifactFilters = {
  keyword: "",
  artifactType: "all",
  runId: "",
};

describe("Task 05 Studio operations data", () => {
  it("meets source health floors and named source coverage", () => {
    const sourceNames = new Set(sources.map((source) => source.name));
    const healthStatuses = new Set(sources.map((source) => source.healthStatus));

    expect(sources.length).toBeGreaterThanOrEqual(8);
    expect([...sourceNames]).toEqual(
      expect.arrayContaining([
        "OpenAI Blog",
        "Anthropic Blog",
        "Google DeepMind Blog",
        "GitHub Trending",
        "HackerNews",
        "Reddit LocalLLaMA",
        "arXiv cs.AI",
        "RSS 自定义来源",
      ]),
    );
    expect([...healthStatuses]).toEqual(expect.arrayContaining(["healthy", "degraded", "failed", "disabled"]));
  });

  it("meets memory floors for evidence, entities, topics, and agent notes", () => {
    expect(memoryItems.length).toBeGreaterThanOrEqual(20);
    expect(memoryItems.filter((item) => item.type === "evidence").length).toBeGreaterThanOrEqual(8);
    expect(memoryItems.filter((item) => item.type === "entity").length).toBeGreaterThanOrEqual(5);
    expect(memoryItems.filter((item) => (item.topicIds?.length ?? 0) > 0).length).toBeGreaterThanOrEqual(5);
    expect(memoryItems.filter((item) => item.type === "agent_note").length).toBeGreaterThanOrEqual(3);
  });

  it("meets quality result floors and check dimension coverage", () => {
    const objectTypes = new Set(qualityResults.map((result) => result.objectType));
    const statuses = new Set(qualityResults.map((result) => result.status));
    const checkNames = new Set(qualityResults.flatMap((result) => result.checks.map((check) => check.name)));
    const expectedChecks: QualityCheck["name"][] = [
      "sourceCoverage",
      "factConsistency",
      "duplicateRisk",
      "summaryCompleteness",
      "titleQuality",
      "evidenceCompleteness",
      "citationQuality",
      "humanReviewRequired",
    ];

    expect(qualityResults.length).toBeGreaterThanOrEqual(20);
    expect([...objectTypes]).toEqual(expect.arrayContaining(["news", "topic", "report", "run"]));
    expect([...statuses]).toEqual(expect.arrayContaining(["passed", "warning", "failed", "review_required"]));
    expect(qualityResults.filter((result) => result.status === "review_required").length).toBeGreaterThanOrEqual(5);
    expect(qualityResults.filter((result) => result.status === "failed").length).toBeGreaterThanOrEqual(3);
    expect([...checkNames]).toEqual(expect.arrayContaining(expectedChecks));
  });

  it("meets artifact type coverage and tolerates metadata-only previews", () => {
    expect(artifactTypeCounts(artifacts)).toMatchObject({
      json: expect.any(Number),
      markdown: expect.any(Number),
      html: expect.any(Number),
      log: expect.any(Number),
      report: expect.any(Number),
      dataset: expect.any(Number),
    });
    expect(artifacts.some((artifact) => !artifact.preview)).toBe(true);
  });
});

describe("Task 05 Studio operations filters", () => {
  it("filters sources by keyword, health, type, and enabled state", () => {
    expect(filterSources(sources, { ...allSourceFilters, keyword: "reddit" }).map((source) => source.id)).toEqual(["reddit-localllama"]);
    expect(filterSources(sources, { ...allSourceFilters, healthStatus: "failed" }).every((source) => source.healthStatus === "failed")).toBe(true);
    expect(filterSources(sources, { ...allSourceFilters, type: "official_blog" }).every((source) => source.type === "official_blog")).toBe(true);
    expect(filterSources(sources, { ...allSourceFilters, enabled: "disabled" }).every((source) => !source.enabled)).toBe(true);
  });

  it("filters memory by keyword, type, confidence, entity, and topic", () => {
    const filters: MemoryFilters = { keyword: "OpenAI", memoryType: ["evidence"], confidence: ["high"], entity: "OpenAI", topicId: "agent-runtime-observability" };
    const results = filterMemoryItems(memoryItems, filters);

    expect(results.length).toBeGreaterThan(0);
    expect(results.every((item) => item.type === "evidence")).toBe(true);
    expect(results.every((item) => item.confidence === "high")).toBe(true);
    expect(results.every((item) => item.entityNames?.includes("OpenAI") ?? false)).toBe(true);
    expect(results.every((item) => item.topicIds?.includes("agent-runtime-observability") ?? false)).toBe(true);
  });

  it("filters quality results by type, status, score, and review state", () => {
    expect(filterQualityResults(qualityResults, { ...allQualityFilters, objectType: "run" }).every((result) => result.objectType === "run")).toBe(true);
    expect(filterQualityResults(qualityResults, { ...allQualityFilters, status: "failed" }).every((result) => result.status === "failed")).toBe(true);
    expect(filterQualityResults(qualityResults, { ...allQualityFilters, minScore: 80 }).every((result) => result.score >= 80)).toBe(true);
    expect(filterQualityResults(qualityResults, { ...allQualityFilters, review: "pending" }).every((result) => result.reviewerDecision === "pending")).toBe(true);
  });

  it("filters artifacts by keyword, type, and run id", () => {
    expect(filterArtifacts(artifacts, { ...allArtifactFilters, keyword: "quality" }).every((artifact) => [artifact.filename, artifact.id, artifact.runId, artifact.stepId, artifact.artifactType].join(" ").toLowerCase().includes("quality"))).toBe(true);
    expect(filterArtifacts(artifacts, { ...allArtifactFilters, artifactType: "json" }).every((artifact) => artifact.artifactType === "json")).toBe(true);
    expect(filterArtifacts(artifacts, { ...allArtifactFilters, runId: "run-daily-001" }).every((artifact) => artifact.runId.includes("run-daily-001"))).toBe(true);
  });
});
