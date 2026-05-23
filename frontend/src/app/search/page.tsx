import { Suspense } from "react";
import { PageSkeleton } from "@/components/common/loading-skeleton";
import { SearchPageClient } from "@/app/search/search-page-client";

export default function SearchPage() {
  return (
    <Suspense fallback={<PageSkeleton />}>
      <SearchPageClient />
    </Suspense>
  );
}
