import { NextRequest } from "next/server"
import { getProjectList } from "@/lib/projects/data-source"
import { backendGet, backendPath, buildCaseResult, failure, projectParams, success } from "@/lib/projects/v1-route-data"
import type { ProjectsApiCaseResult } from "@/types/projects"

export const dynamic = "force-dynamic"

export async function GET(request: NextRequest) {
  const backend = await backendGet<ProjectsApiCaseResult>(backendPath("/api/v1/projects/cases", request.nextUrl.searchParams))
  if (backend.ok) return success(backend.data)

  try {
    const result = await getProjectList(projectParams(request.nextUrl.searchParams, { sort: "quality" }))
    return success(buildCaseResult(result))
  } catch (error) {
    return failure(500, "projects_cases_fallback_failed", error instanceof Error ? error.message : "Projects cases fallback failed")
  }
}
