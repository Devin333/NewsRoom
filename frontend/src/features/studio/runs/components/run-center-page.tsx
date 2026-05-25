"use client"

import { useState } from "react"
import { Search } from "lucide-react"
import { ErrorState } from "@/components/common/error-state"
import { Input } from "@/components/ui/input"
import { RunListTable } from "@/features/studio/runs/components/run-list-table"
import { RunStatusSummary } from "@/features/studio/runs/components/run-status-summary"
import { useRunList } from "@/features/studio/runs/hooks/use-run-list"
import { StudioNotice, StudioPageHeader, StudioToolbar } from "@/features/studio/shared/components/studio-dashboard"
import type { AgentRunFilters, AgentRunStatus, StudioRunListItem } from "@/types/agent"

const statuses: AgentRunStatus[] = ["pending", "running", "success", "failed", "partially_failed", "blocked", "waiting_for_human", "cancelled"]

export function RunCenterPage({ runs, notices = [] }: { runs: StudioRunListItem[]; notices?: string[] }) {
  const [filters, setFilters] = useState<AgentRunFilters>({ sort: "startedAt" })
  const { data, isError, error } = useRunList(filters, runs)
  const workflows = unique(runs.map((run) => run.workflowId ?? run.workflowName ?? run.agentName))
  const profiles = unique(runs.map((run) => run.profile))

  return (
    <main className="space-y-6">
      <StudioPageHeader
        eyebrow="Runtime"
        title="Run Center"
        description="Inspect workflow runs, status, runtime health, quality, errors, events, and artifacts from the live Run Runtime API."
      />
      {notices.length ? (
        <StudioNotice title="Run data notice">
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
              placeholder="Search runs, workflows, profiles"
              value={filters.keyword ?? ""}
              onChange={(event) => setFilters({ ...filters, keyword: event.target.value || undefined })}
            />
          </label>
          <Select label="Workflow" value={filters.workflowId?.[0] ?? ""} options={workflows} onChange={(value) => setFilters({ ...filters, workflowId: value ? [value] : undefined })} />
          <Select label="Status" value={filters.status?.[0] ?? ""} options={statuses} onChange={(value) => setFilters({ ...filters, status: value ? [value as AgentRunStatus] : undefined })} />
          <Select label="Profile" value={filters.profile?.[0] ?? ""} options={profiles} onChange={(value) => setFilters({ ...filters, profile: value ? [value] : undefined })} />
          <Select
            label="Sort"
            value={filters.sort ?? "startedAt"}
            options={["startedAt", "durationMs", "qualityScore", "errorCount"]}
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
            Errors only
          </label>
          <label className="inline-flex items-center gap-2 rounded-md border border-border px-3 py-2 text-sm text-muted-foreground">
            Minimum quality
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
      {isError ? <ErrorState message={error instanceof Error ? error.message : "Run list failed to load."} /> : <RunListTable runs={data} />}
    </main>
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
      <select className="h-9 rounded-md border border-input bg-background px-3 text-sm text-foreground" value={value} onChange={(event) => onChange(event.target.value)}>
        <option value="">All</option>
        {options.map((option) => (
          <option key={option} value={option}>
            {labelOption(option)}
          </option>
        ))}
      </select>
    </label>
  )
}

function unique(values: Array<string | undefined>): string[] {
  return Array.from(new Set(values.filter((value): value is string => Boolean(value)))).sort()
}

function labelOption(option: string) {
  const labels: Record<string, string> = {
    startedAt: "Started",
    durationMs: "Duration",
    qualityScore: "Quality",
    errorCount: "Errors",
    pending: "Pending",
    running: "Running",
    success: "Success",
    failed: "Failed",
    partially_failed: "Partially failed",
    blocked: "Blocked",
    waiting_for_human: "Waiting for human",
    cancelled: "Cancelled"
  }
  return labels[option] ?? option
}
