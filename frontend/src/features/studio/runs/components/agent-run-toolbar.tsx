"use client"

import { Search } from "lucide-react"
import { Input } from "@/components/ui/input"
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
  const agents = Array.from(new Set(runs.map((run) => run.agentName))).sort()
  const profiles = Array.from(new Set(runs.map((run) => run.profile))).sort()

  return (
    <div className="rounded-lg border border-border bg-card p-4">
      <div className="grid gap-3 lg:grid-cols-[minmax(240px,1fr)_180px_180px_160px_150px_150px]">
        <label className="relative">
          <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
          <Input
            className="pl-9"
            placeholder="搜索运行、智能体、配置"
            value={filters.keyword ?? ""}
            onChange={(event) => onFiltersChange({ ...filters, keyword: event.target.value || undefined })}
          />
        </label>
        <Select
          label="智能体"
          value={filters.agentName?.[0] ?? ""}
          options={agents}
          onChange={(value) => onFiltersChange({ ...filters, agentName: value ? [value] : undefined })}
        />
        <Select
          label="状态"
          value={filters.status?.[0] ?? ""}
          options={statuses}
          onChange={(value) => onFiltersChange({ ...filters, status: value ? [value as AgentRunStatus] : undefined })}
        />
        <Select
          label="配置"
          value={filters.profile?.[0] ?? ""}
          options={profiles}
          onChange={(value) => onFiltersChange({ ...filters, profile: value ? [value] : undefined })}
        />
        <Select
          label="范围"
          value={filters.dateRange ?? ""}
          options={["today", "week", "month"]}
          onChange={(value) => onFiltersChange({ ...filters, dateRange: value ? (value as AgentRunFilters["dateRange"]) : undefined })}
        />
        <Select
          label="排序"
          value={filters.sort ?? "startedAt"}
          options={["startedAt", "durationMs", "qualityScore", "errorCount"]}
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
          仅错误
        </label>
        <label className="inline-flex items-center gap-2 rounded-md border border-border px-3 py-2 text-sm text-muted-foreground">
          最低质量
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
  onChange
}: {
  label: string
  value: string
  options: string[]
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
        <option value="">全部</option>
        {options.map((option) => (
          <option key={option} value={option}>
            {labelOption(option)}
          </option>
        ))}
      </select>
    </label>
  )
}

function labelOption(option: string) {
  const labels: Record<string, string> = {
    today: "今天",
    week: "本周",
    month: "本月",
    startedAt: "开始时间",
    durationMs: "耗时",
    qualityScore: "质量分",
    errorCount: "错误数",
    running: "运行中",
    success: "成功",
    failed: "失败",
    partially_failed: "部分失败",
    cancelled: "已取消",
  }
  return labels[option] ?? option
}
