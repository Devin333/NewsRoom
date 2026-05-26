import { Suspense } from "react";
import { PageSkeleton } from "@/components/common/loading-skeleton";
import { TopicsPageClient } from "@/app/topics/topics-page-client";
import { EvidenceGraphPage } from "@/features/portal/evidence-graph-page";
import { getEvidenceGraphData } from "@/features/portal/portal-home-data";

export const dynamic = "force-dynamic";

export default async function TopicsPage({
  searchParams,
}: {
  searchParams?: { view?: string };
}) {
  if (searchParams?.view === "evidence-graph") {
    const data = await getEvidenceGraphData();
    return <EvidenceGraphPage data={data} />;
  }

  return (
    <Suspense fallback={<PageSkeleton />}>
      <TopicsPageClient />
    </Suspense>
  );
}
