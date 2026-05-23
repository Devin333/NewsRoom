import { EmptyState } from "@/components/common/empty-state"
import { NewsCard } from "@/features/news/components/news-card"
import { NewsTable } from "@/features/news/components/news-table"
import type { NewsItem, NewsViewMode } from "@/types/news"

export function NewsList({ items, viewMode }: { items: NewsItem[]; viewMode: NewsViewMode }) {
  if (!items.length) {
    return (
      <EmptyState
        title="没有匹配的新闻"
        description="可以移除一两个筛选条件，或切回最新发布排序。"
      />
    )
  }

  if (viewMode === "table") {
    return <NewsTable items={items} />
  }

  return (
    <div className="border-t border-border">
      {items.map((item) => (
        <NewsCard key={item.id} news={item} compact={viewMode === "dense"} />
      ))}
    </div>
  )
}
