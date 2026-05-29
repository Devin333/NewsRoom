import { NextRequest } from "next/server"
import { proxyBackendMutation } from "@/lib/projects/v1-route-data"
import type { ProjectsToolRecommendResult } from "@/types/projects"

export const dynamic = "force-dynamic"

export async function POST(request: NextRequest) {
  return proxyBackendMutation<ProjectsToolRecommendResult>("/api/v1/projects/tools/recommend", await request.json())
}
