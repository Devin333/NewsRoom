import Link from "next/link"
import { Suspense } from "react"
import { RunTable } from "@/components/runs/RunTable"
import { EmptyState } from "@/components/common/EmptyState"
import { Pagination } from "@/components/common/Pagination"
import { FilterBar } from "@/components/common/FilterBar"
import { safeApiGet } from "@/lib/api-client"
import type { RunList } from "@/lib/types"

const STATUSES = ["all", "running", "succeeded", "failed", "blocked", "cancelled"]

const RUN_FILTERS = [
  { key: "q", label: "Search run ID…", type: "text" as const },
  { key: "from", label: "From date", type: "date" as const },
  { key: "to", label: "To date", type: "date" as const },
]

export default async function RunsPage({
  searchParams
}: {
  searchParams: Promise<{ status?: string; limit?: string; offset?: string; q?: string; from?: string; to?: string }>
}) {
  const sp = await searchParams
  const status = STATUSES.includes(sp.status ?? "") ? sp.status : undefined
  const limit = Math.min(100, Math.max(1, Number(sp.limit) || 20))
  const offset = Math.max(0, Number(sp.offset) || 0)

  const qs = new URLSearchParams({ limit: String(limit), offset: String(offset) })
  if (status) qs.set("status", status)
  if (sp.from) qs.set("started_after", sp.from)
  if (sp.to) qs.set("started_before", sp.to)

  const res = await safeApiGet<RunList>(`/api/v1/runs?${qs}`)
  // client-side keyword filter (run_id prefix match)
  let runs = res.data?.runs ?? []
  if (sp.q) runs = runs.filter((r) => r.run_id.includes(sp.q!) || (r.workflow_id ?? "").includes(sp.q!))

  function pageHref(newOffset: number) {
    const p = new URLSearchParams()
    if (status) p.set("status", status)
    p.set("limit", String(limit))
    p.set("offset", String(newOffset))
    if (sp.q) p.set("q", sp.q)
    if (sp.from) p.set("from", sp.from)
    if (sp.to) p.set("to", sp.to)
    return `/runs?${p}`
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-xl font-semibold text-ink">Runs</h1>
        <p className="mt-0.5 text-sm text-muted">Workflow execution history</p>
      </div>

      <div className="flex flex-wrap items-center gap-2">
        {STATUSES.map((s) => {
          const active = (s === "all" && !status) || s === status
          const href = s === "all" ? `/runs?limit=${limit}` : `/runs?status=${s}&limit=${limit}`
          return (
            <Link key={s} href={href}
              className={`rounded-full px-3 py-1 text-xs font-medium transition-colors ${
                active ? "bg-ink text-white" : "bg-white border border-line text-muted hover:text-ink"
              }`}
            >
              {s}
            </Link>
          )
        })}
        <div className="ml-auto flex items-center gap-1.5 text-xs text-muted">
          Show
          {[20, 50, 100].map((n) => (
            <Link key={n} href={`/runs?${status ? `status=${status}&` : ""}limit=${n}`}
              className={`rounded px-2 py-0.5 ${limit === n ? "bg-ink text-white" : "hover:text-ink"}`}
            >
              {n}
            </Link>
          ))}
        </div>
      </div>

      <Suspense>
        <FilterBar filters={RUN_FILTERS} />
      </Suspense>

      <div className="rounded-xl border border-line bg-white p-5 shadow-card">
        {res.ok && runs.length ? (
          <>
            <RunTable runs={runs} />
            <Pagination href={pageHref} offset={offset} limit={limit} count={runs.length} />
          </>
        ) : (
          <EmptyState title="No runs found" message={res.errorMessage} />
        )}
      </div>
    </div>
  )
}
