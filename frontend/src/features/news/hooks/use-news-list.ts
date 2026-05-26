"use client"

import { useQuery } from "@tanstack/react-query"
import { fetchNewsList } from "@/lib/news/api"
import { queryKeys } from "@/lib/query/query-keys"
import type { NewsFilters } from "@/types/news"

export function useNewsList(filters: NewsFilters) {
  return useQuery({
    queryKey: queryKeys.news.list(filters),
    queryFn: () => fetchNewsList(filters)
  })
}
