import { NextRequest } from "next/server"
import { getProjectList } from "@/lib/projects/data-source"
import {
  backendGet,
  backendPath,
  buildCollectionResult,
  failure,
  projectParams,
  proxyBackendMutation,
  success,
} from "@/lib/projects/v1-route-data"
import type { ProjectsApiCollectionResult, ProjectsCollectionMutationResult } from "@/types/projects"

export const dynamic = "force-dynamic"

export async function GET(request: NextRequest) {
  const backend = await backendGet<ProjectsApiCollectionResult>(backendPath("/api/v1/projects/collections", request.nextUrl.searchParams))
  if (backend.ok) return success(backend.data)

  try {
    const result = await getProjectList(projectParams(request.nextUrl.searchParams, { limit: 100 }))
    return success(buildCollectionResult(result))
  } catch (error) {
    return failure(500, "projects_collections_fallback_failed", error instanceof Error ? error.message : "Projects collections fallback failed")
  }
}

export async function POST(request: NextRequest) {
  return proxyBackendMutation<ProjectsCollectionMutationResult>("/api/v1/projects/collections", await request.json())
}
