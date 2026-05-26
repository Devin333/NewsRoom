"use client"

import { useQuery } from "@tanstack/react-query"
import { fetchNewsDetail } from "@/lib/news/api"
import { queryKeys } from "@/lib/query/query-keys"

export function useNewsDetail(id: string) {
  return useQuery({
    queryKey: queryKeys.news.detail(id),
    queryFn: () => fetchNewsDetail(id)
  })
}
