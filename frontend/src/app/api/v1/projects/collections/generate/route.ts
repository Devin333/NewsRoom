import { NextRequest } from "next/server"
import { proxyBackendMutation } from "@/lib/projects/v1-route-data"
import type { ProjectsCollectionMutationResult } from "@/types/projects"

export const dynamic = "force-dynamic"

export async function POST(request: NextRequest) {
  return proxyBackendMutation<ProjectsCollectionMutationResult>("/api/v1/projects/collections/generate", await request.json())
}
