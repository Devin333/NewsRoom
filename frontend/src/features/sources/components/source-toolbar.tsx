"use client"

import { Search } from "lucide-react"
import { StudioToolbar } from "@/features/studio/shared/components/studio-dashboard"
import { formatStatus } from "@/lib/i18n"
import { useI18n } from "@/lib/i18n/use-i18n"
import type { SourceType } from "@/types/common"
import type { SourceFilters, SourceHealthStatus } from "@/types/source"

const sourceTypes: SourceType[] = [
  "official_blog",
  "rss",
  "atom",
  "github",
  "hackernews",
  "reddit",
  "arxiv",
  "lobsters",
  "stackoverflow",
  "devto",
  "medium",
  "html",
  "web_page",
  "manual",
  "media",
  "custom"
]

const healthStatuses: SourceHealthStatus[] = ["healthy", "degraded", "failed", "down", "cooling_down", "disabled"]

export function SourceToolbar({ filters, onChange }: { filters: SourceFilters; onChange: (filters: SourceFilters) => void }) {
  const { locale, t } = useI18n()
  return (
    <StudioToolbar>
      <div className="grid gap-3 lg:grid-cols-[minmax(260px,1fr)_12rem_12rem_12rem]">
        <label className="relative">
          <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
          <input
            className="h-10 w-full rounded-md border border-input bg-background px-3 pl-9 text-sm text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            placeholder={t("studio.sources.searchPlaceholder")}
            value={filters.keyword}
            onChange={(event) => onChange({ ...filters, keyword: event.target.value })}
          />
        </label>
        <Select label={t("studio.sources.type")} locale={locale} value={filters.type} options={["all", ...sourceTypes]} onChange={(value) => onChange({ ...filters, type: value as SourceFilters["type"] })} />
        <Select label={t("studio.sources.health")} locale={locale} value={filters.healthStatus} options={["all", ...healthStatuses]} onChange={(value) => onChange({ ...filters, healthStatus: value as SourceFilters["healthStatus"] })} />
        <Select label={t("studio.sources.enabled")} locale={locale} value={filters.enabled} options={["all", "enabled", "disabled"]} onChange={(value) => onChange({ ...filters, enabled: value as SourceFilters["enabled"] })} />
      </div>
    </StudioToolbar>
  )
}

function Select({ label, locale, value, options, onChange }: { label: string; locale: "zh" | "en"; value: string; options: string[]; onChange: (value: string) => void }) {
  return (
    <label className="grid gap-1 text-xs text-muted-foreground">
      {label}
      <select className="h-10 rounded-md border border-input bg-background px-3 text-sm text-foreground" value={value} onChange={(event) => onChange(event.target.value)}>
        {options.map((option) => (
          <option key={option} value={option}>
            {formatOption(locale, option)}
          </option>
        ))}
      </select>
    </label>
  )
}

function formatOption(locale: "zh" | "en", value: string): string {
  if (value === "all") return locale === "zh" ? "全部" : "All"
  if (value === "enabled") return locale === "zh" ? "已启用" : "Enabled"
  if (value === "disabled") return locale === "zh" ? "已禁用" : "Disabled"
  const translatedStatus = formatStatus(locale, value)
  if (translatedStatus !== value.replace(/[_-]+/g, " ").replace(/\b\w/g, (letter) => letter.toUpperCase())) {
    return translatedStatus
  }
  return value
    .split("_")
    .filter(Boolean)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ")
}
