export type TocItem = {
  id: string;
  title: string;
  depth: number;
};

export function extractToc(markdown: string): TocItem[] {
  return markdown
    .split("\n")
    .filter((line) => /^#{1,3}\s/.test(line))
    .map((line) => {
      const depth = line.match(/^#+/)?.[0].length ?? 1;
      const title = line.replace(/^#+\s*/, "").trim();
      return {
        id: title.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, ""),
        title,
        depth,
      };
    });
}

export function ReportToc({ markdown }: { markdown: string }) {
  const items = extractToc(markdown);
  return (
    <section className="rounded-lg border border-border bg-card p-4">
      <h2 className="text-base font-semibold text-foreground">目录</h2>
      <div className="mt-3 space-y-2">
        {items.map((item) => (
          <p key={item.id} className="text-sm text-muted-foreground" style={{ paddingLeft: `${(item.depth - 1) * 12}px` }}>
            {item.title}
          </p>
        ))}
      </div>
    </section>
  );
}
