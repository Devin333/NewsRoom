import Link from "next/link"
import { ErrorState } from "@/components/common/ErrorState"
import { RunTable } from "@/components/runs/RunTable"
import { safeApiGet } from "@/lib/api-client"
import type { RunList } from "@/lib/types"

const RUN_STATUS_OPTIONS = ["running", "succeeded", "failed", "blocked", "cancelled"]

export default async function RunsPage({
  searchParams
}: {
  searchParams: { status?: string; limit?: string }
}) {
  const limit = normalizeLimit(searchParams.limit)
  const status = searchParams.status || undefined
  const query = new URLSearchParams({ limit: String(limit) })
  if (status) {
    query.set("status", status)
  }
  const runs = await safeApiGet<RunList>(`/api/v1/runs?${query.toString()}`)

  return (
    <main className="space-y-6">
      <header className="flex flex-col gap-4 border-b border-line pb-4 lg:flex-row lg:items-end lg:justify-between">
        <div>
          <h1 className="text-2xl font-semibold text-ink">Runs</h1>
          <p className="text-sm text-muted">Workflow run history and current execution status.</p>
        </div>
        <div className="flex flex-wrap gap-2">
          <FilterLink active={!status} href={`/runs?limit=${limit}`} label="All" />
          {RUN_STATUS_OPTIONS.map((option) => (
            <FilterLink
              key={option}
              active={status === option}
              href={`/runs?status=${option}&limit=${limit}`}
              label={option}
            />
          ))}
        </div>
      </header>

      {runs.ok && runs.data ? (
        <RunTable runs={runs.data.runs ?? []} />
      ) : (
        <ErrorState message={runs.errorMessage} requestId={runs.requestId} />
      )}
    </main>
  )
}

function FilterLink({ active, href, label }: { active: boolean; href: string; label: string }) {
  return (
    <Link
      href={href}
      className={`rounded-md border px-3 py-2 text-sm font-medium ${
        active ? "border-accent bg-accent text-white" : "border-line bg-white text-muted hover:text-ink"
      }`}
    >
      {label}
    </Link>
  )
}

function normalizeLimit(value?: string): number {
  const parsed = Number(value)
  if (!Number.isFinite(parsed) || parsed < 1) {
    return 20
  }
  return Math.min(Math.floor(parsed), 100)
}
