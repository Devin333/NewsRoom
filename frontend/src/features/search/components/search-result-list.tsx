import { EmptyState } from "@/components/common/empty-state";
import type { SearchResult } from "@/types/search";
import { SearchResultCard } from "./search-result-card";

export function SearchResultList({ results }: { results: SearchResult[] }) {
  if (!results.length) {
    return <EmptyState title="暂无搜索结果" description="尝试其他查询，或包含更多对象类型。" />;
  }
  return (
    <div className="space-y-3">
      {results.map((result) => (
        <SearchResultCard key={`${result.objectType}-${result.id}`} result={result} />
      ))}
    </div>
  );
}
