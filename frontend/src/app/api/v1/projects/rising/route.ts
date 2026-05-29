import { NextRequest } from "next/server"
import { getProjectList } from "@/lib/projects/data-source"
import { backendGet, backendPath, buildListResult, failure, projectParams, success } from "@/lib/projects/v1-route-data"
import type { ProjectsApiListResult } from "@/types/projects"

export const dynamic = "force-dynamic"

export async function GET(request: NextRequest) {
  const backend = await backendGet<ProjectsApiListResult>(backendPath("/api/v1/projects/rising", request.nextUrl.searchParams))
  if (backend.ok) return success(backend.data)

  try {
    const result = await getProjectList(projectParams(request.nextUrl.searchParams, { sort: "growth" }))
    return success(buildListResult(result, "rising"))
  } catch (error) {
    return failure(500, "projects_rising_fallback_failed", error instanceof Error ? error.message : "Projects rising fallback failed")
  }
}
