import { additionalSearchResults, evidences, newsItems, reports, techItems, topics } from "@/lib/mock-data";
import { titleCase } from "@/lib/format";
import type { SearchObjectType, SearchResult } from "@/types/search";

export const searchObjectTypes: SearchObjectType[] = [
  "news",
  "topic",
  "report",
  "evidence",
  "tech",
  "memory",
  "source",
  "agent_run",
];

export function buildSearchIndex(): SearchResult[] {
  const newsResults = newsItems.map<SearchResult>((item) => ({
    id: item.id,
    objectType: "news",
    title: item.title,
    summary: item.summary,
    matchedSnippet: item.summary,
    timestamp: item.publishedAt,
    tags: item.tags,
    sourceName: item.sourceName,
    relevanceScore: item.heatScore,
    href: `/search?type=news&q=${encodeURIComponent(item.title)}`,
  }));

  const topicResults = topics.map<SearchResult>((topic) => ({
    id: topic.id,
    objectType: "topic",
    title: topic.name,
    summary: topic.summary,
    matchedSnippet: topic.executiveSummary ?? topic.summary,
    timestamp: topic.lastSeenAt,
    tags: topic.tags ?? [],
    relevanceScore: topic.heatScore,
    href: `/topics/${topic.id}`,
  }));

  const reportResults = reports.map<SearchResult>((report) => ({
    id: report.id,
    objectType: "report",
    title: report.title,
    summary: `${titleCase(report.reportType ?? report.type ?? "generated")}报告，由 ${report.agentName ?? "Agora Hub Agent"} 生成`,
    matchedSnippet: (report.markdown ?? "").slice(0, 220),
    timestamp: report.generatedAt,
    tags: [report.reportType ?? report.type ?? "report", report.status],
    relevanceScore: report.qualityScore,
    href: `/reports/${report.id}`,
  }));

  const evidenceResults = evidences.map<SearchResult>((evidence) => ({
    id: evidence.id,
    objectType: "evidence",
    title: evidence.title,
    summary: evidence.summary,
    matchedSnippet: evidence.quote ?? evidence.summary,
    timestamp: evidence.capturedAt,
    tags: [evidence.sourceType, evidence.credibility],
    sourceName: evidence.sourceName,
    relevanceScore: evidence.confidenceScore,
    href: evidence.originalUrl ?? evidence.sourceUrl ?? "#",
  }));

  const techResults = techItems.map<SearchResult>((item) => ({
    id: item.id,
    objectType: "tech",
    title: item.name,
    summary: item.summary,
    matchedSnippet: item.agentEvaluation,
    timestamp: item.updatedAt ?? item.createdAt,
    tags: [item.type, item.maturity, ...item.tags],
    relevanceScore: item.maturity === "stable" || item.maturity === "mature" ? 86 : 74,
    href: item.sourceUrl,
  }));

  return [...topicResults, ...newsResults, ...reportResults, ...evidenceResults, ...techResults, ...additionalSearchResults];
}

export function searchIndex(query: string, types: SearchObjectType[] = searchObjectTypes) {
  const normalized = query.trim().toLowerCase();
  return buildSearchIndex()
    .filter((result) => types.includes(result.objectType))
    .filter((result) => {
      if (!normalized) {
        return true;
      }
      const haystack = [result.title, result.summary, result.matchedSnippet, result.sourceName, ...(result.tags ?? [])]
        .filter(Boolean)
        .join(" ")
        .toLowerCase();
      return haystack.includes(normalized);
    })
    .sort((a, b) => (b.relevanceScore ?? 0) - (a.relevanceScore ?? 0));
}
