export type { Artifact } from "@/types/agent"

export type ArtifactFilters = {
  keyword: string
  artifactType: "all" | "json" | "markdown" | "html" | "log" | "report" | "dataset"
  runId: string
}
