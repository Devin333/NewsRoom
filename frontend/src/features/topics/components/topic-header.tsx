import { HeatScoreBadge, QualityBadge, TrendBadge } from "@/components/common/badges";
import { ScoreMeter } from "@/components/common/score-meter";
import { formatDate } from "@/lib/format";
import type { Topic } from "@/types/topic";

export function TopicHeader({ topic }: { topic: Topic }) {
  return (
    <section className="rounded-lg border border-border bg-card p-5">
      <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
        <div>
          <div className="flex flex-wrap gap-2">
            <TrendBadge trend={topic.trend} />
            <HeatScoreBadge score={topic.heatScore} />
            <QualityBadge score={topic.qualityScore ?? 0} />
          </div>
          <h1 className="mt-4 text-2xl font-semibold text-foreground">{topic.name}</h1>
          <p className="mt-3 max-w-4xl text-sm leading-6 text-muted-foreground">{topic.summary}</p>
        </div>
        <div className="grid min-w-64 gap-3">
          <ScoreMeter label="热度" value={topic.heatScore} />
          <ScoreMeter label="质量" value={topic.qualityScore ?? 0} />
        </div>
      </div>
      <div className="mt-5 grid gap-3 text-sm md:grid-cols-4">
        <Metric label="新闻" value={String(topic.itemCount)} />
        <Metric label="来源" value={String(topic.sourceCount)} />
        <Metric label="首次出现" value={formatDate(topic.firstSeenAt)} />
        <Metric label="更新于" value={formatDate(topic.lastSeenAt)} />
      </div>
      <div className="mt-4 flex flex-wrap gap-2">
        {[...(topic.entities ?? []), ...(topic.tags ?? []).map((tag) => `#${tag}`)].map((item) => (
          <span key={item} className="rounded-md bg-secondary px-2 py-1 text-xs text-muted-foreground">
            {item}
          </span>
        ))}
      </div>
    </section>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-md border border-border bg-background/60 p-3">
      <p className="text-xs text-muted-foreground">{label}</p>
      <p className="mt-1 font-medium text-foreground">{value}</p>
    </div>
  );
}
