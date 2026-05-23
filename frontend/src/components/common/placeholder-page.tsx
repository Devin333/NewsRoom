import { PageHeader } from "@/components/layout/page-header"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"

export type PlaceholderPageProps = {
  eyebrow: string
  title: string
  description: string
  focus: string[]
}

export function PlaceholderPage({ eyebrow, title, description, focus }: PlaceholderPageProps) {
  return (
    <div className="space-y-6">
      <PageHeader eyebrow={eyebrow} title={title} description={description} />
      <Card>
        <CardHeader>
          <CardTitle>规划中的工作区</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="grid gap-3 md:grid-cols-3">
            {focus.map((item) => (
              <div key={item} className="rounded-md border border-border bg-secondary/60 p-4 text-sm leading-6 text-muted-foreground">
                {item}
              </div>
            ))}
          </div>
        </CardContent>
      </Card>
    </div>
  )
}
