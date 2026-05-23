import Link from "next/link"
import { CredibilityBadge } from "@/components/common/credibility-badge"
import { HeatScoreBadge } from "@/components/common/heat-score-badge"
import { QualityBadge } from "@/components/common/quality-badge"
import { SourceBadge } from "@/components/common/source-badge"
import { formatDateTime } from "@/lib/format"
import type { NewsItem } from "@/types/news"

export function NewsTable({ items }: { items: NewsItem[] }) {
  return (
    <div className="overflow-x-auto rounded-lg border border-border bg-card">
      <table className="w-full min-w-[980px] table-fixed text-left text-sm">
        <thead className="border-b border-border text-xs uppercase text-muted-foreground">
          <tr>
            <th className="w-[34%] px-4 py-3 font-medium">标题</th>
            <th className="w-[15%] px-4 py-3 font-medium">来源</th>
            <th className="w-[12%] px-4 py-3 font-medium">分类</th>
            <th className="w-[10%] px-4 py-3 font-medium">热度</th>
            <th className="w-[11%] px-4 py-3 font-medium">质量</th>
            <th className="w-[12%] px-4 py-3 font-medium">可信度</th>
            <th className="w-[14%] px-4 py-3 font-medium">发布时间</th>
            <th className="w-[16%] px-4 py-3 font-medium">主题</th>
          </tr>
        </thead>
        <tbody>
          {items.map((item) => (
            <tr key={item.id} className="border-b border-border last:border-0">
              <td className="px-4 py-3">
                <Link href={`/news/${item.id}`} className="line-clamp-2 font-medium text-foreground hover:text-accent">
                  {item.title}
                </Link>
              </td>
              <td className="px-4 py-3">
                <SourceBadge type={item.sourceType} />
              </td>
              <td className="px-4 py-3 text-muted-foreground">{item.category}</td>
              <td className="px-4 py-3">
                <HeatScoreBadge value={item.heatScore} />
              </td>
              <td className="px-4 py-3">
                <QualityBadge value={item.qualityScore} />
              </td>
              <td className="px-4 py-3">
                <CredibilityBadge value={item.credibility} />
              </td>
              <td className="px-4 py-3 text-muted-foreground">{formatDateTime(item.publishedAt)}</td>
              <td className="px-4 py-3">
                {item.topicId && item.topicName ? (
                  <Link href={`/topics/${item.topicId}`} className="text-accent hover:text-foreground">
                    {item.topicName}
                  </Link>
                ) : (
                  <span className="text-muted-foreground">未聚类</span>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
