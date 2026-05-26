"use client"

import { useMemo } from "react"
import { useQuery } from "@tanstack/react-query"
import { useRouter, useSearchParams } from "next/navigation"
import { EmptyState } from "@/components/common/empty-state"
import { ErrorState } from "@/components/common/error-state"
import { PageSkeleton } from "@/components/common/loading-skeleton"
import { CommunityPulsePage } from "@/features/community/components/community-pulse-page"
import { fetchCommunityTopics } from "@/lib/community/api"
import {
  communityFiltersFromSearchParams,
  communityFiltersToSearchParams,
  updateCommunityFilters
} from "@/lib/community/community-filters"
import type { CommunityListParams } from "@/types/community"

export function CommunityPageClient() {
  const router = useRouter()
  const searchParams = useSearchParams()
  const filters = useMemo(
    () => communityFiltersFromSearchParams(new URLSearchParams(searchParams.toString())),
    [searchParams]
  )
  const { data, isLoading, isError, error, refetch } = useQuery({
    queryKey: ["community", "topics", filters],
    queryFn: () => fetchCommunityTopics(filters)
  })

  const setFilters = (patch: Partial<CommunityListParams>) => {
    const next = updateCommunityFilters(filters, patch)
    const params = communityFiltersToSearchParams(next)
    router.replace(params.size ? `/community?${params.toString()}` : "/community", { scroll: false })
  }

  if (isLoading) return <PageSkeleton />

  if (isError) {
    return <ErrorState message={error instanceof Error ? error.message : "Community Pulse failed to load."} onRetry={() => refetch()} />
  }

  if (!data) {
    return <EmptyState title="No community data" description="Community Pulse data is currently unavailable." />
  }

  return <CommunityPulsePage result={data} filters={filters} onChange={setFilters} />
}
