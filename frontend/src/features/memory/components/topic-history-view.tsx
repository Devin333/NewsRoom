import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { formatDateTime, formatNumber } from "@/lib/format";
import type { MemoryItem } from "@/types/memory";

export function TopicHistoryView({ items }: { items: MemoryItem[] }) {
  const topics = new Map<string, MemoryItem[]>();
  items.forEach((item) => item.topicIds?.forEach((topicId) => topics.set(topicId, [...(topics.get(topicId) ?? []), item])));

  return (
    <div className="space-y-3">
      {[...topics.entries()].map(([topicId, topicItems]) => {
        const sorted = [...topicItems].sort((a, b) => new Date(a.createdAt).getTime() - new Date(b.createdAt).getTime());
        const latest = sorted[sorted.length - 1];
        return (
          <Card key={topicId}>
            <CardHeader><CardTitle>{topicId}</CardTitle></CardHeader>
            <CardContent className="space-y-3 text-sm text-muted-foreground">
              <div className="grid gap-2 sm:grid-cols-3">
                <p>{formatNumber(topicItems.length)} 条记忆</p>
                <p>首次出现 {formatDateTime(sorted[0]?.createdAt)}</p>
                <p>最近更新 {formatDateTime(latest?.createdAt)}</p>
              </div>
              <div className="space-y-2">
                {sorted.slice(-3).map((item) => (
                  <div key={item.id} className="rounded-md border border-border bg-secondary/40 p-3">
                    <p className="font-medium text-foreground">{item.title}</p>
                    <p className="mt-1">{item.summary}</p>
                  </div>
                ))}
              </div>
            </CardContent>
          </Card>
        );
      })}
    </div>
  );
}
