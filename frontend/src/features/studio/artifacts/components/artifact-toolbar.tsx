"use client";

import type { ArtifactFilters } from "@/types/artifact";

const artifactTypes: Array<Exclude<ArtifactFilters["artifactType"], "all">> = ["json", "markdown", "html", "log", "report", "dataset"];
const artifactLabels: Record<Exclude<ArtifactFilters["artifactType"], "all">, string> = {
  json: "JSON",
  markdown: "Markdown",
  html: "HTML",
  log: "日志",
  report: "报告",
  dataset: "数据集",
};

export function ArtifactToolbar({ filters, onChange }: { filters: ArtifactFilters; onChange: (filters: ArtifactFilters) => void }) {
  return (
    <section className="grid gap-3 rounded-lg border border-border bg-card p-4 lg:grid-cols-[1fr_12rem_12rem]">
      <input className="h-10 rounded-md border border-input bg-background px-3 text-sm" placeholder="搜索产物" value={filters.keyword} onChange={(event) => onChange({ ...filters, keyword: event.target.value })} />
      <select className="h-10 rounded-md border border-input bg-background px-3 text-sm" value={filters.artifactType} onChange={(event) => onChange({ ...filters, artifactType: event.target.value as ArtifactFilters["artifactType"] })}>
        <option value="all">全部类型</option>
        {artifactTypes.map((type) => <option key={type} value={type}>{artifactLabels[type]}</option>)}
      </select>
      <input className="h-10 rounded-md border border-input bg-background px-3 text-sm" placeholder="运行 ID" value={filters.runId} onChange={(event) => onChange({ ...filters, runId: event.target.value })} />
    </section>
  );
}
