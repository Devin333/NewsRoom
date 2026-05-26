import { EvidenceGraphExplorer } from "@/features/evidence-graph/evidence-graph-explorer"
import type { EvidenceGraphResponse } from "@/types/evidence-graph"

export function EvidenceGraphPage({ data }: { data: EvidenceGraphResponse }) {
  return <EvidenceGraphExplorer data={data} />
}
