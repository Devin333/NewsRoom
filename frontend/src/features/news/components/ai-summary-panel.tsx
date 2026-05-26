export function AISummaryPanel({
  summary,
  whyItMatters,
}: {
  summary?: string
  whyItMatters?: string
}) {
  return (
    <section className="rounded-lg border border-border bg-card p-5">
      <h2 className="text-lg font-semibold text-foreground">AI 摘要</h2>
      <p className="mt-3 text-sm leading-6 text-muted-foreground">{summary ?? "这条新闻暂无详细 AI 摘要。"}</p>
      <div className="mt-5 rounded-md border border-border bg-secondary/50 p-4">
        <p className="text-xs font-medium uppercase text-accent">为什么重要</p>
        <p className="mt-2 text-sm leading-6 text-foreground">{whyItMatters ?? "暂无重要性分析。"}</p>
      </div>
    </section>
  )
}
