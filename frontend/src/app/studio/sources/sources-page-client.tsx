"use client"

import { SourceDetailPanel } from "@/features/sources/components/source-detail-panel"
import { SourceHealthTable } from "@/features/sources/components/source-health-table"
import { SourceMetrics } from "@/features/sources/components/source-metrics"
import { SourceToolbar } from "@/features/sources/components/source-toolbar"
import { useSources } from "@/features/sources/hooks/use-sources"
import { StudioNotice, StudioPageHeader } from "@/features/studio/shared/components/studio-dashboard"

export function SourcesPageClient() {
  const {
    allSources,
    sources,
    filters,
    setFilters,
    selectedSource,
    setSelectedSourceId,
    isLoading,
    isFetchingPreview,
    error,
    isUsingMockFallback
  } = useSources()

  return (
    <div className="space-y-6">
      <StudioPageHeader
        eyebrow="System"
        title="Sources"
        description="Monitor source registry health, collection freshness, failure signals, and connector coverage."
      />

      {isLoading ? (
        <StudioNotice tone="info" title="Loading sources">
          Reading source registry from the NewsRoom API.
        </StudioNotice>
      ) : null}
      {error ? (
        <StudioNotice tone="warning" title="Source fallback active">
          Real API is unavailable. Showing fallback source data: {error instanceof Error ? error.message : "request failed"}.
        </StudioNotice>
      ) : null}
      {!error && !isUsingMockFallback ? (
        <StudioNotice tone="success" title="Source registry connected">
          Loaded {allSources.length} sources from the live registry.{isFetchingPreview ? " Fetching selected source preview." : ""}
        </StudioNotice>
      ) : null}

      <SourceMetrics sources={allSources} />
      <SourceToolbar filters={filters} onChange={setFilters} />
      <SourceHealthTable sources={sources} selectedSourceId={selectedSource?.id} onSelectSource={setSelectedSourceId} />
      <SourceDetailPanel source={selectedSource} />
    </div>
  )
}
