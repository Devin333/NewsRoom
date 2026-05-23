import { Suspense } from "react";
import { PageSkeleton } from "@/components/common/loading-skeleton";
import { TopicsPageClient } from "@/app/topics/topics-page-client";

export default function TopicsPage() {
  return (
    <Suspense fallback={<PageSkeleton />}>
      <TopicsPageClient />
    </Suspense>
  );
}
