import { EmptyState } from "@/components/common/empty-state";
import { MemoryCard } from "@/features/memory/components/memory-card";
import type { MemoryItem } from "@/types/memory";

export function MemoryResultList({ items }: { items: MemoryItem[] }) {
  if (!items.length) {
    return <EmptyState title="暂无记忆结果" description="尝试更换关键词、实体、主题、类型或可信度筛选。" />;
  }

  return (
    <div className="space-y-3">
      {items.map((item) => <MemoryCard key={item.id} item={item} />)}
    </div>
  );
}
