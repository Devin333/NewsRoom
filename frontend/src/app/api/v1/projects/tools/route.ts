import { NextRequest } from "next/server"
import { getProjectList } from "@/lib/projects/data-source"
import { backendGet, backendPath, buildToolResult, failure, projectParams, success } from "@/lib/projects/v1-route-data"
import type { ProjectsApiToolResult } from "@/types/projects"

export const dynamic = "force-dynamic"

export async function GET(request: NextRequest) {
  const backend = await backendGet<ProjectsApiToolResult>(backendPath("/api/v1/projects/tools", request.nextUrl.searchParams))
  if (backend.ok) return success(backend.data)

  try {
    const result = await getProjectList(projectParams(request.nextUrl.searchParams, { sort: "activity" }))
    return success(buildToolResult(result))
  } catch (error) {
    return failure(500, "projects_tools_fallback_failed", error instanceof Error ? error.message : "Projects tools fallback failed")
  }
}
