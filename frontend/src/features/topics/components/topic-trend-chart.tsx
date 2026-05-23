import type { Topic } from "@/types/topic";

export function TopicTrendChart({ topic }: { topic: Topic }) {
  const history = topic.trendHistory ?? [{ date: "现在", heatScore: topic.heatScore, itemCount: topic.itemCount }];
  const max = Math.max(...history.map((point) => point.heatScore));
  return (
    <section className="rounded-lg border border-border bg-card p-4">
      <h2 className="text-base font-semibold text-foreground">趋势图</h2>
      <div className="mt-4 flex h-44 items-end gap-2">
        {history.map((point) => (
          <div key={point.date} className="flex flex-1 flex-col items-center gap-2">
            <div className="w-full rounded-t bg-primary/80" style={{ height: `${Math.max(12, (point.heatScore / max) * 145)}px` }} />
            <span className="text-[10px] text-muted-foreground">{point.date}</span>
          </div>
        ))}
      </div>
    </section>
  );
}
