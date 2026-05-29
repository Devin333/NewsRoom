import { NextRequest } from "next/server"
import { getProjectList } from "@/lib/projects/data-source"
import {
  backendGet,
  backendPath,
  buildHomeResult,
  failure,
  projectParams,
  success,
} from "@/lib/projects/v1-route-data"
import type { ProjectsApiHomeResult } from "@/types/projects"

export const dynamic = "force-dynamic"

export async function GET(request: NextRequest) {
  const backend = await backendGet<ProjectsApiHomeResult>(backendPath("/api/v1/projects", request.nextUrl.searchParams))
  if (backend.ok) return success(backend.data)

  try {
    const limit = Number(request.nextUrl.searchParams.get("limit") ?? 6)
    const result = await getProjectList(projectParams(request.nextUrl.searchParams, { sort: "trending", limit }))
    return success(buildHomeResult(result, Number.isFinite(limit) ? limit : 6))
  } catch (error) {
    return failure(500, "projects_home_fallback_failed", error instanceof Error ? error.message : "Projects home fallback failed")
  }
}
