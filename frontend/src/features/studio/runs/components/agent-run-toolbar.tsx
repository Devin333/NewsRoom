"use client"

import { Search } from "lucide-react"
import { Input } from "@/components/ui/input"
import { useI18n } from "@/lib/i18n/use-i18n"
import type { AgentRun, AgentRunFilters, AgentRunStatus } from "@/types/agent"

const statuses: AgentRunStatus[] = ["running", "success", "failed", "partially_failed", "cancelled"]

export function AgentRunToolbar({
  runs,
  filters,
  onFiltersChange
}: {
  runs: AgentRun[]
  filters: AgentRunFilters
  onFiltersChange: (filters: AgentRunFilters) => void
}) {
  const { t, status } = useI18n()
  const agents = Array.from(new Set(runs.map((run) => run.agentName))).sort()
  const profiles = Array.from(new Set(runs.map((run) => run.profile))).sort()

  return (
    <div className="rounded-lg border border-border bg-card p-4">
      <div className="grid gap-3 lg:grid-cols-[minmax(240px,1fr)_180px_180px_160px_150px_150px]">
        <label className="relative">
          <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
          <Input
            className="pl-9"
            placeholder={t("studio.runs.searchPlaceholder")}
            value={filters.keyword ?? ""}
            onChange={(event) => onFiltersChange({ ...filters, keyword: event.target.value || undefined })}
          />
        </label>
        <Select
          label={t("studio.runs.agent")}
          value={filters.agentName?.[0] ?? ""}
          options={agents}
          allLabel={t("studio.runs.all")}
          onChange={(value) => onFiltersChange({ ...filters, agentName: value ? [value] : undefined })}
        />
        <Select
          label={t("common.status")}
          value={filters.status?.[0] ?? ""}
          options={statuses}
          allLabel={t("studio.runs.all")}
          optionLabel={(value) => status(value)}
          onChange={(value) => onFiltersChange({ ...filters, status: value ? [value as AgentRunStatus] : undefined })}
        />
        <Select
          label={t("studio.runs.profile")}
          value={filters.profile?.[0] ?? ""}
          options={profiles}
          allLabel={t("studio.runs.all")}
          onChange={(value) => onFiltersChange({ ...filters, profile: value ? [value] : undefined })}
        />
        <Select
          label={t("studio.runs.range")}
          value={filters.dateRange ?? ""}
          options={["today", "week", "month"]}
          allLabel={t("studio.runs.all")}
          optionLabel={(value) => {
            if (value === "today") return t("common.today")
            if (value === "week") return t("common.thisWeek")
            if (value === "month") return t("common.thisMonth")
            return value
          }}
          onChange={(value) => onFiltersChange({ ...filters, dateRange: value ? (value as AgentRunFilters["dateRange"]) : undefined })}
        />
        <Select
          label={t("studio.runs.sort")}
          value={filters.sort ?? "startedAt"}
          options={["startedAt", "durationMs", "qualityScore", "errorCount"]}
          allLabel={t("studio.runs.all")}
          optionLabel={(value) => t(`studio.runs.sort.${value}`)}
          onChange={(value) => onFiltersChange({ ...filters, sort: value as AgentRunFilters["sort"] })}
        />
      </div>
      <div className="mt-3 flex flex-wrap gap-2">
        <label className="inline-flex items-center gap-2 rounded-md border border-border px-3 py-2 text-sm text-muted-foreground">
          <input
            type="checkbox"
            checked={Boolean(filters.hasError)}
            onChange={(event) => onFiltersChange({ ...filters, hasError: event.target.checked || undefined })}
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
            onChange={(event) =>
              onFiltersChange({ ...filters, minQualityScore: event.target.value ? Number(event.target.value) : undefined })
            }
          />
        </label>
      </div>
    </div>
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
      <select
        className="h-9 rounded-md border border-input bg-background px-3 text-sm text-foreground"
        value={value}
        onChange={(event) => onChange(event.target.value)}
      >
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
