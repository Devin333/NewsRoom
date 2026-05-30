import { SourceHealthTable } from "@/components/sources/SourceHealthTable"
import { EmptyState } from "@/components/common/EmptyState"
import { safeApiGet } from "@/lib/api-client"
import type { SourceHealthResponse } from "@/lib/types"

export default async function SourcesPage({
  searchParams
}: {
  searchParams: Promise<{ disabled?: string }>
}) {
  const sp = await searchParams
  const includeDisabled = sp.disabled === "true"
  const res = await safeApiGet<SourceHealthResponse>(
    `/api/v1/sources/health?include_disabled=${includeDisabled}`
  )
  const sources = res.data?.sources ?? res.data?.health ?? []

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-semibold text-ink">Sources</h1>
          <p className="mt-0.5 text-sm text-muted">Data source health and status</p>
        </div>
        <a
          href={includeDisabled ? "/sources" : "/sources?disabled=true"}
          className="text-xs text-accent hover:underline"
        >
          {includeDisabled ? "Hide disabled" : "Show disabled"}
        </a>
      </div>

      <div className="rounded-xl border border-line bg-white p-5 shadow-card">
        {res.ok && sources.length ? (
          <SourceHealthTable sources={sources} />
        ) : (
          <EmptyState title="No sources found" message={res.errorMessage} />
        )}
      </div>
    </div>
  )
}
