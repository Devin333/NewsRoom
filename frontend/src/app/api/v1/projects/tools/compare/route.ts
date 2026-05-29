import { NextRequest } from "next/server"
import { proxyBackendMutation } from "@/lib/projects/v1-route-data"
import type { ProjectsToolCompareResult } from "@/types/projects"

export const dynamic = "force-dynamic"

export async function POST(request: NextRequest) {
  return proxyBackendMutation<ProjectsToolCompareResult>("/api/v1/projects/tools/compare", await request.json())
}
