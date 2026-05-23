import { EmptyState } from "@/components/common/empty-state";
import { cn } from "@/lib/format";
import type { Topic } from "@/types/topic";
import { TopicCard } from "./topic-card";

export function TopicList({ topics, viewMode }: { topics: Topic[]; viewMode: "grid" | "list" | "dense" }) {
  if (!topics.length) {
    return <EmptyState title="没有匹配的主题" description="尝试放宽关键词、趋势、分类或实体筛选。" />;
  }

  return (
    <div className={cn(viewMode === "grid" && "grid gap-4 md:grid-cols-2 xl:grid-cols-3", viewMode !== "grid" && "space-y-3")}>
      {topics.map((topic) => (
        <TopicCard key={topic.id} topic={topic} dense={viewMode === "dense"} />
      ))}
    </div>
  );
}
