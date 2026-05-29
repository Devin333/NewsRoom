import { NextRequest } from "next/server"
import { getProjectList } from "@/lib/projects/data-source"
import {
  backendGet,
  backendPath,
  buildWatchlistResult,
  failure,
  projectParams,
  proxyBackendMutation,
  success,
} from "@/lib/projects/v1-route-data"
import type { ProjectsApiWatchlistResult, ProjectsWatchlistItemResponse } from "@/types/projects"

export const dynamic = "force-dynamic"

export async function GET(request: NextRequest) {
  const backend = await backendGet<ProjectsApiWatchlistResult>(backendPath("/api/v1/projects/watchlist", request.nextUrl.searchParams))
  if (backend.ok) return success(backend.data)

  try {
    const result = await getProjectList(projectParams(request.nextUrl.searchParams, { limit: 1 }))
    return success(buildWatchlistResult(result))
  } catch (error) {
    return failure(500, "projects_watchlist_fallback_failed", error instanceof Error ? error.message : "Projects watchlist fallback failed")
  }
}

export async function POST(request: NextRequest) {
  return proxyBackendMutation<ProjectsWatchlistItemResponse>("/api/v1/projects/watchlist", await request.json())
}
