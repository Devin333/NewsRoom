import { ErrorState } from "@/components/common/ErrorState"
import { SourceHealthTable } from "@/components/sources/SourceHealthTable"
import { safeApiGet } from "@/lib/api-client"
import type { SourceHealthItem, SourceHealthResponse } from "@/lib/types"

export default async function SourcesPage() {
  const health = await safeApiGet<SourceHealthResponse>("/api/v1/sources/health?include_disabled=true")
  const sources = normalizeSources(health.data)

  return (
    <main className="space-y-6">
      <header className="border-b border-line pb-4">
        <h1 className="text-2xl font-semibold text-ink">Sources</h1>
        <p className="text-sm text-muted">Source health, cooldowns, and consecutive failure counts.</p>
      </header>

      {health.ok ? (
        <SourceHealthTable sources={sources} />
      ) : (
        <ErrorState message={health.errorMessage} requestId={health.requestId} />
      )}
    </main>
  )
}

function normalizeSources(data?: SourceHealthResponse): SourceHealthItem[] {
  return data?.sources ?? data?.health ?? []
}
