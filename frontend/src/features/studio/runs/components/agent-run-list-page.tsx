"use client"

import { useState } from "react"
import { ErrorState } from "@/components/common/error-state"
import { PageHeader } from "@/components/layout/page-header"
import { AgentRunTable } from "@/features/studio/runs/components/agent-run-table"
import { AgentRunToolbar } from "@/features/studio/runs/components/agent-run-toolbar"
import { useAgentRuns } from "@/features/studio/runs/hooks/use-agent-runs"
import type { AgentRun, AgentRunFilters } from "@/types/agent"

export function AgentRunListPage({ runs, notices = [] }: { runs: AgentRun[]; notices?: string[] }) {
  const [filters, setFilters] = useState<AgentRunFilters>({ sort: "startedAt" })
  const { data, isError, error } = useAgentRuns(filters, runs)

  return (
    <main className="space-y-6">
      <PageHeader
        eyebrow="Studio"
        title="智能体运行"
        description="高密度运行历史，包含状态、耗时、输入输出量、产物、质量和错误数。"
      />
      {notices.length ? (
        <section className="rounded-lg border border-warning/30 bg-warning/10 p-4">
          {notices.map((notice) => (
            <p key={notice} className="text-sm text-warning">
              {notice}
            </p>
          ))}
        </section>
      ) : null}
      <AgentRunToolbar runs={runs} filters={filters} onFiltersChange={setFilters} />
      {isError ? <ErrorState message={error instanceof Error ? error.message : "智能体运行加载失败。"} /> : <AgentRunTable runs={data} />}
    </main>
  )
}
