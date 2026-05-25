"use client";

import { useI18n } from "@/lib/i18n/use-i18n";
import type { ArtifactFilters } from "@/types/artifact";

const artifactTypes: Array<Exclude<ArtifactFilters["artifactType"], "all">> = ["json", "markdown", "html", "log", "report", "dataset"];
const artifactLabels: Record<Exclude<ArtifactFilters["artifactType"], "all">, { zh: string; en: string }> = {
  json: { zh: "JSON", en: "JSON" },
  markdown: { zh: "Markdown", en: "Markdown" },
  html: { zh: "HTML", en: "HTML" },
  log: { zh: "日志", en: "Log" },
  report: { zh: "报告", en: "Report" },
  dataset: { zh: "数据集", en: "Dataset" },
};

export function ArtifactToolbar({ filters, onChange }: { filters: ArtifactFilters; onChange: (filters: ArtifactFilters) => void }) {
  const { locale, t } = useI18n();
  return (
    <section className="grid gap-3 rounded-lg border border-border bg-card p-4 lg:grid-cols-[1fr_12rem_12rem]">
      <input className="h-10 rounded-md border border-input bg-background px-3 text-sm" placeholder={t("studio.artifacts.searchArtifacts")} value={filters.keyword} onChange={(event) => onChange({ ...filters, keyword: event.target.value })} />
      <select className="h-10 rounded-md border border-input bg-background px-3 text-sm" value={filters.artifactType} onChange={(event) => onChange({ ...filters, artifactType: event.target.value as ArtifactFilters["artifactType"] })}>
        <option value="all">{t("studio.artifacts.allTypes")}</option>
        {artifactTypes.map((type) => <option key={type} value={type}>{artifactLabels[type][locale]}</option>)}
      </select>
      <input className="h-10 rounded-md border border-input bg-background px-3 text-sm" placeholder={t("studio.review.runId")} value={filters.runId} onChange={(event) => onChange({ ...filters, runId: event.target.value })} />
    </section>
  );
}
