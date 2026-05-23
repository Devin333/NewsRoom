import type { AgentAnalysis } from "@/types/topic";

export function AgentAnalysisPanel({ analyses }: { analyses: AgentAnalysis[] }) {
  return (
    <section className="rounded-lg border border-border bg-card p-4">
      <h2 className="text-base font-semibold text-foreground">智能体分析</h2>
      <div className="mt-4 space-y-3">
        {analyses.map((analysis) => (
          <div key={analysis.agent} className="rounded-md border border-border bg-background/50 p-3">
            <p className="text-sm font-medium text-foreground">{analysis.agent}</p>
            <p className="mt-1 text-sm leading-6 text-muted-foreground">{analysis.summary}</p>
          </div>
        ))}
      </div>
    </section>
  );
}
