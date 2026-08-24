import { notFound } from "next/navigation"
import { StatusBadge } from "@/components/common/StatusBadge"
import { RunTimeline } from "@/components/runs/RunTimeline"
import { RunLiveEvents } from "@/components/runs/RunLiveEvents"
import { RunArtifacts } from "@/components/runs/RunArtifacts"
import { RunOperationPanel } from "@/components/runs/RunOperationPanel"
import { EmptyState } from "@/components/common/EmptyState"
import { safeApiGet } from "@/lib/api-client"
import { formatDateTime, stringifyJson } from "@/lib/format"
import type { RunDetail, RunEvents, RunArtifacts as RunArtifactsType, RunDiagnostics } from "@/lib/types"

export default async function RunDetailPage({ params }: { params: Promise<{ runId: string }> }) {
  const { runId } = await params
  const [run, events, artifacts, diagnostics] = await Promise.all([
    safeApiGet<RunDetail>(`/api/v2/graph-runs/${encodeURIComponent(runId)}`),
    safeApiGet<RunEvents>(`/api/v2/graph-runs/${encodeURIComponent(runId)}/events`),
    safeApiGet<RunArtifactsType>(`/api/v2/graph-runs/${encodeURIComponent(runId)}/artifacts`),
    safeApiGet<RunDiagnostics>(`/api/v2/graph-runs/${encodeURIComponent(runId)}/diagnostics`)
  ])

  if (!run.ok || !run.data) return notFound()
  const r = run.data
  const isLive = r.status === "running" || r.status === "queued"

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="font-mono text-lg font-semibold text-ink">{runId}</h1>
          <p className="mt-0.5 text-sm text-muted">{r.graph_ref ?? r.graph_id ?? "Unknown graph"}{r.profile ? ` · ${r.profile}` : ""}</p>
        </div>
        <StatusBadge status={r.status} />
      </div>

      {/* Meta grid */}
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        {[
          { label: "Started", value: r.started_at ? formatDateTime(r.started_at) : "—" },
          { label: "Finished", value: r.finished_at ? formatDateTime(r.finished_at) : "—" },
          { label: "Report", value: r.report_id?.slice(0, 12) ?? "—" },
          { label: "Graph version", value: r.graph_version ?? "—" }
        ].map(({ label, value }) => (
          <div key={label} className="rounded-lg border border-line bg-white p-3 shadow-card">
            <p className="text-xs font-medium text-muted">{label}</p>
            <p className="mt-1 truncate font-mono text-xs text-ink">{value}</p>
          </div>
        ))}
      </div>

      <div className="grid gap-6 lg:grid-cols-3">
        {/* Left: events + operations */}
        <div className="lg:col-span-2 space-y-6">
          {/* Operations */}
          <Section title="Operations">
            <RunOperationPanel runId={runId} />
          </Section>

          {/* Events */}
          <Section title={isLive ? "Live Events" : "Events"}>
            {isLive ? (
              <RunLiveEvents runId={runId} />
            ) : events.data?.events?.length ? (
              <RunTimeline events={events.data.events} />
            ) : (
              <EmptyState title="No events" />
            )}
          </Section>

          {/* Artifacts */}
          <Section title="Artifacts">
            <RunArtifacts artifacts={artifacts.data?.artifacts ?? []} />
          </Section>
        </div>

        {/* Right: manifest + diagnostics */}
        <div className="space-y-6">
          {r.manifest && (
            <Section title="Manifest">
              <pre className="overflow-x-auto rounded-md bg-surface p-3 font-mono text-xs text-ink">
                {stringifyJson(r.manifest)}
              </pre>
            </Section>
          )}
          {diagnostics.data?.diagnostics && (
            <Section title="Diagnostics">
              <pre className="overflow-x-auto rounded-md bg-surface p-3 font-mono text-xs text-ink">
                {stringifyJson(diagnostics.data.diagnostics)}
              </pre>
            </Section>
          )}
        </div>
      </div>
    </div>
  )
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="rounded-xl border border-line bg-white p-5 shadow-card">
      <h2 className="mb-4 text-sm font-semibold text-ink">{title}</h2>
      {children}
    </div>
  )
}
