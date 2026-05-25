"use client"

import { useState } from "react"
import { Search } from "lucide-react"
import { ErrorState } from "@/components/common/error-state"
import { Input } from "@/components/ui/input"
import { RunListTable } from "@/features/studio/runs/components/run-list-table"
import { RunStatusSummary } from "@/features/studio/runs/components/run-status-summary"
import { useRunList } from "@/features/studio/runs/hooks/use-run-list"
import { StudioNotice, StudioPageHeader, StudioToolbar } from "@/features/studio/shared/components/studio-dashboard"
import { useI18n } from "@/lib/i18n/use-i18n"
import type { AgentRunFilters, AgentRunStatus, StudioRunListItem } from "@/types/agent"

const statuses: AgentRunStatus[] = ["pending", "running", "success", "failed", "partially_failed", "blocked", "waiting_for_human", "cancelled"]

export function RunCenterPage({ runs, notices = [] }: { runs: StudioRunListItem[]; notices?: string[] }) {
  const { t, status } = useI18n()
  const [filters, setFilters] = useState<AgentRunFilters>({ sort: "startedAt" })
  const { data, isError, error } = useRunList(filters, runs)
  const workflows = unique(runs.map((run) => run.workflowId ?? run.workflowName ?? run.agentName))
  const profiles = unique(runs.map((run) => run.profile))

  return (
    <main className="space-y-6">
      <StudioPageHeader
        eyebrow={t("studio.nav.runtime")}
        title={t("studio.module.runCenter.title")}
        description={t("studio.module.runCenter.description")}
      />
      {notices.length ? (
        <StudioNotice title={t("studio.runs.dataNotice")}>
          {notices.map((notice) => (
            <p key={notice}>
              {notice}
            </p>
          ))}
        </StudioNotice>
      ) : null}
      <RunStatusSummary runs={runs} />
      <StudioToolbar>
        <div className="grid gap-3 lg:grid-cols-[minmax(240px,1fr)_180px_180px_160px_150px]">
          <label className="relative">
            <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
            <Input
              className="pl-9"
              placeholder={t("studio.runs.searchPlaceholder")}
              value={filters.keyword ?? ""}
              onChange={(event) => setFilters({ ...filters, keyword: event.target.value || undefined })}
            />
          </label>
          <Select label={t("studio.runs.workflow")} value={filters.workflowId?.[0] ?? ""} options={workflows} allLabel={t("studio.runs.all")} onChange={(value) => setFilters({ ...filters, workflowId: value ? [value] : undefined })} />
          <Select label={t("common.status")} value={filters.status?.[0] ?? ""} options={statuses} allLabel={t("studio.runs.all")} optionLabel={(value) => status(value)} onChange={(value) => setFilters({ ...filters, status: value ? [value as AgentRunStatus] : undefined })} />
          <Select label={t("studio.runs.profile")} value={filters.profile?.[0] ?? ""} options={profiles} allLabel={t("studio.runs.all")} onChange={(value) => setFilters({ ...filters, profile: value ? [value] : undefined })} />
          <Select
            label={t("studio.runs.sort")}
            value={filters.sort ?? "startedAt"}
            options={["startedAt", "durationMs", "qualityScore", "errorCount"]}
            allLabel={t("studio.runs.all")}
            optionLabel={(value) => t(`studio.runs.sort.${value}`)}
            onChange={(value) => setFilters({ ...filters, sort: value as AgentRunFilters["sort"] })}
          />
        </div>
        <div className="mt-3 flex flex-wrap gap-2">
          <label className="inline-flex items-center gap-2 rounded-md border border-border px-3 py-2 text-sm text-muted-foreground">
            <input
              type="checkbox"
              checked={Boolean(filters.hasError)}
              onChange={(event) => setFilters({ ...filters, hasError: event.target.checked || undefined })}
            />
            {t("studio.runs.errorsOnly")}
          </label>
          <label className="inline-flex items-center gap-2 rounded-md border border-border px-3 py-2 text-sm text-muted-foreground">
            {t("studio.runs.minimumQuality")}
            <input
              className="h-6 w-16 rounded border border-border bg-background px-2 text-foreground"
              type="number"
              min={0}
              max={100}
              value={filters.minQualityScore ?? ""}
              onChange={(event) => setFilters({ ...filters, minQualityScore: event.target.value ? Number(event.target.value) : undefined })}
            />
          </label>
        </div>
      </StudioToolbar>
      {isError ? <ErrorState message={error instanceof Error ? error.message : t("studio.runs.listFailed")} /> : <RunListTable runs={data} />}
    </main>
  )
}

function Select({
  label,
  value,
  options,
  allLabel,
  optionLabel,
  onChange
}: {
  label: string
  value: string
  options: string[]
  allLabel?: string
  optionLabel?: (value: string) => string
  onChange: (value: string) => void
}) {
  return (
    <label className="grid gap-1 text-xs text-muted-foreground">
      {label}
      <select className="h-9 rounded-md border border-input bg-background px-3 text-sm text-foreground" value={value} onChange={(event) => onChange(event.target.value)}>
        <option value="">{allLabel ?? "All"}</option>
        {options.map((option) => (
          <option key={option} value={option}>
            {optionLabel?.(option) ?? option}
          </option>
        ))}
      </select>
    </label>
  )
}

function unique(values: Array<string | undefined>): string[] {
  return Array.from(new Set(values.filter((value): value is string => Boolean(value)))).sort()
}
