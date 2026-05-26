import { Suspense } from "react";
import { PageSkeleton } from "@/components/common/loading-skeleton";
import { TopicsPageClient } from "@/app/topics/topics-page-client";
import { EvidenceGraphPage } from "@/features/evidence-graph/evidence-graph-page";
import { evidenceGraphQueryFromRecord, getEvidenceGraphData } from "@/features/evidence-graph/evidence-graph-data";

export const dynamic = "force-dynamic";

export default async function TopicsPage({
  searchParams,
}: {
  searchParams?: Record<string, string | string[] | undefined>;
}) {
  if (searchParams?.view === "evidence-graph") {
    const data = await getEvidenceGraphData(evidenceGraphQueryFromRecord(searchParams));
    return <EvidenceGraphPage data={data} />;
  }

  return (
    <Suspense fallback={<PageSkeleton />}>
      <TopicsPageClient />
    </Suspense>
  );
}
