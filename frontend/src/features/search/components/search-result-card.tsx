import Link from "next/link";
import { Badge } from "@/components/common/badges";
import { formatDateTime, titleCase } from "@/lib/format";
import type { SearchResult } from "@/types/search";

export function SearchResultCard({ result }: { result: SearchResult }) {
  const external = result.href.startsWith("http");
  return (
    <Link href={result.href} target={external ? "_blank" : undefined} className="block rounded-lg border border-border bg-card p-4 transition hover:border-primary/60">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="text-base font-semibold text-foreground">{result.title}</h2>
          <p className="mt-1 text-xs text-muted-foreground">
            {titleCase(result.objectType)} {result.timestamp ? `· ${formatDateTime(result.timestamp)}` : null}
          </p>
        </div>
        <Badge tone="accent">相关度 {Math.round(result.relevanceScore ?? 0)}</Badge>
      </div>
      {result.summary ? <p className="mt-3 text-sm leading-6 text-muted-foreground">{result.summary}</p> : null}
      {result.matchedSnippet ? <p className="mt-3 rounded-md border border-border bg-background/50 p-3 text-xs text-muted-foreground">{result.matchedSnippet}</p> : null}
      <div className="mt-3 flex flex-wrap gap-1">
        {result.tags?.map((tag) => (
          <span key={tag} className="rounded bg-secondary px-2 py-1 text-xs text-muted-foreground">
            #{tag}
          </span>
        ))}
      </div>
    </Link>
  );
}
