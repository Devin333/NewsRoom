import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { EmptyState } from "@/components/common/empty-state";

export function MarkdownViewer({ markdown }: { markdown?: string }) {
  if (!markdown?.trim()) {
    return <EmptyState title="暂无 Markdown 内容" description="这份报告还没有可阅读的 Markdown 正文。" />;
  }

  return (
    <article className="markdown-body rounded-lg border border-border bg-card p-5">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          a: ({ href, children }) => (
            <a href={href} target={href?.startsWith("http") ? "_blank" : undefined} rel="noreferrer">
              {children}
            </a>
          ),
        }}
      >
        {markdown}
      </ReactMarkdown>
    </article>
  );
}
