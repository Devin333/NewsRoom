"use client"

import { useQuery } from "@tanstack/react-query"
import { fetchDashboardOverview } from "@/lib/dashboard/api"
import { queryKeys } from "@/lib/query/query-keys"

export function useDashboardOverview() {
  return useQuery({
    queryKey: queryKeys.dashboard,
    queryFn: fetchDashboardOverview
  })
}
