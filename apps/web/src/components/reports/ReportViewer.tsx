export function ReportViewer({ markdown }: { markdown: string }) {
  return (
    <div className="prose prose-sm max-w-none">
      <pre className="whitespace-pre-wrap rounded-lg border border-line bg-surface p-5 font-sans text-sm leading-relaxed text-ink">
        {markdown}
      </pre>
    </div>
  )
}
