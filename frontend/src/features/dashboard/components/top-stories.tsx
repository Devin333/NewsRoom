import Link from "next/link"
import { NewsCard } from "@/features/news/components/news-card"
import type { NewsItem } from "@/types/news"

export function TopStories({ stories }: { stories: NewsItem[] }) {
  return (
    <section className="space-y-4">
      <div className="flex items-center justify-between gap-3">
        <h2 className="text-lg font-semibold text-foreground">重点新闻</h2>
        <Link href="/news?sort=heatScore" className="text-sm text-accent hover:text-foreground">
          查看全部
        </Link>
      </div>
      <div className="grid gap-3">
        {stories.map((story) => (
          <NewsCard key={story.id} news={story} compact />
        ))}
      </div>
    </section>
  )
}
