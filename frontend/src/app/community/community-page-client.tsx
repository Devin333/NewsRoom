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
    return <ErrorState message={error instanceof Error ? error.message : "社区脉搏加载失败。"} onRetry={() => refetch()} />
  }

  if (!data) {
    return <EmptyState title="暂无社区数据" description="当前没有可展示的社区脉搏数据。" />
  }

  return <CommunityPulsePage result={data} filters={filters} onChange={setFilters} />
}
