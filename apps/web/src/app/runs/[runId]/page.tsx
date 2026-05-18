import { ErrorState } from "@/components/common/ErrorState"
import { EmptyState } from "@/components/common/EmptyState"
import { StatusBadge } from "@/components/common/StatusBadge"
import { RunArtifacts } from "@/components/runs/RunArtifacts"
import { RunLiveEvents } from "@/components/runs/RunLiveEvents"
import { RunOperationPanel } from "@/components/runs/RunOperationPanel"
import { RunTimeline } from "@/components/runs/RunTimeline"
import { safeApiGet } from "@/lib/api-client"
import { formatDateTime, stringifyJson } from "@/lib/format"
import type { RunArtifacts as RunArtifactsData, RunDetail, RunDiagnostics, RunEvents } from "@/lib/types"

export default async function RunDetailPage({ params }: { params: { runId: string } }) {
  const runId = decodeURIComponent(params.runId)
  const encodedRunId = encodeURIComponent(runId)
  const [run, events, artifacts, diagnostics] = await Promise.all([
    safeApiGet<RunDetail>(`/api/v1/runs/${encodedRunId}`),
    safeApiGet<RunEvents>(`/api/v1/runs/${encodedRunId}/events?limit=50`),
    safeApiGet<RunArtifactsData>(`/api/v1/runs/${encodedRunId}/artifacts`),
    safeApiGet<RunDiagnostics>(`/api/v1/runs/${encodedRunId}/diagnostics`)
  ])

  return (
    <main className="space-y-6">
      <header className="border-b border-line pb-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h1 className="break-all text-2xl font-semibold text-ink">{runId}</h1>
            <p className="text-sm text-muted">Run detail, events, artifacts, and diagnostics.</p>
          </div>
          {run.data?.status ? <StatusBadge status={run.data.status} /> : null}
        </div>
      </header>

      {run.ok && run.data ? (
        <section className="grid gap-4 lg:grid-cols-4">
          <Summary label="Workflow" value={run.data.workflow_id ?? "unknown"} />
          <Summary label="Profile" value={run.data.profile ?? "n/a"} />
          <Summary label="Started" value={formatDateTime(run.data.started_at)} />
          <Summary label="Finished" value={formatDateTime(run.data.finished_at)} />
        </section>
      ) : (
        <ErrorState message={run.errorMessage} requestId={run.requestId} />
      )}

      <section className="grid gap-6 xl:grid-cols-[1fr_1fr]">
        <Panel title="Manifest">
          {run.data?.manifest ? (
            <pre className="max-h-96 overflow-auto whitespace-pre-wrap break-words text-xs text-ink">
              {stringifyJson(run.data.manifest)}
            </pre>
          ) : (
            <EmptyState title="No manifest" message="Manifest data was not returned." />
          )}
        </Panel>
        <Panel title="Diagnostics">
          {diagnostics.ok ? (
            <pre className="max-h-96 overflow-auto whitespace-pre-wrap break-words text-xs text-ink">
              {stringifyJson(diagnostics.data?.diagnostics ?? diagnostics.data)}
            </pre>
          ) : (
            <ErrorState message={diagnostics.errorMessage} requestId={diagnostics.requestId} />
          )}
        </Panel>
      </section>

      <RunOperationPanel runId={runId} />

      <section className="space-y-3">
        <h2 className="text-lg font-semibold text-ink">Events Timeline</h2>
        {events.ok ? (
          <RunLiveEvents runId={runId} initialEvents={events.data?.events ?? []} />
        ) : (
          <ErrorState message={events.errorMessage} requestId={events.requestId} />
        )}
      </section>

      <section className="space-y-3">
        <h2 className="text-lg font-semibold text-ink">Artifacts</h2>
        {artifacts.ok ? (
          <RunArtifacts artifacts={artifacts.data?.artifacts ?? []} />
        ) : (
          <ErrorState message={artifacts.errorMessage} requestId={artifacts.requestId} />
        )}
      </section>

      <section className="space-y-3">
        <h2 className="text-lg font-semibold text-ink">Replay</h2>
        <div className="rounded-lg border border-line bg-white p-4 text-sm text-muted">
          <span className="font-mono text-ink">/api/v1/runs/{runId}/replay</span>
        </div>
      </section>

      <section className="space-y-3">
        <h2 className="text-lg font-semibold text-ink">Live event streams</h2>
        <div className="rounded-lg border border-line bg-white p-4 text-sm text-muted">
          <p><span className="font-mono text-ink">/api/v1/runs/{runId}/progress</span></p>
          <p className="mt-2"><span className="font-mono text-ink">/api/v1/runs/{runId}/events/stream</span></p>
        </div>
      </section>
    </main>
  )
}

function Summary({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border border-line bg-white p-4">
      <p className="text-xs uppercase text-muted">{label}</p>
      <p className="mt-2 truncate font-medium text-ink">{value}</p>
    </div>
  )
}

function Panel({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="rounded-lg border border-line bg-white p-4">
      <h2 className="mb-3 text-base font-semibold text-ink">{title}</h2>
      {children}
    </section>
  )
}
