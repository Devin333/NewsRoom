"use client"

import { useQuery } from "@tanstack/react-query"
import { mockDashboardOverview } from "@/lib/api/mock-data"
import { queryKeys } from "@/lib/query/query-keys"

export function useDashboardOverview() {
  return useQuery({
    queryKey: queryKeys.dashboard,
    queryFn: async () => mockDashboardOverview
  })
}
