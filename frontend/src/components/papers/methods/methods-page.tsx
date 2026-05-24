import { MethodCard } from "@/components/papers/methods/method-card"
import { PapersHero } from "@/components/papers/papers-hero"
import { PapersMicrobar } from "@/components/papers/papers-microbar"
import { papersCopy, t } from "@/lib/papers/copy"
import { papers, paperMethods, paperTasks } from "@/lib/papers/mock-data"
import type { Locale } from "@/lib/papers/types"

export function MethodsPage({ locale }: { locale: Locale }) {
  return (
    <div className="space-y-6">
      <PapersMicrobar items={[{ label: "Methods" }]} meta={t(papersCopy.methodBranch, locale)} locale={locale} />
      <PapersHero
        eyebrow="Papers / Methods"
        title={t(papersCopy.methods, locale)}
        subtitle={t(papersCopy.methodsSubtitle, locale)}
        stats={[
          { label: t(papersCopy.methods, locale), value: paperMethods.length },
          { label: t(papersCopy.papers, locale), value: papers.length },
          { label: t(papersCopy.tasks, locale), value: paperTasks.length }
        ]}
      />
      <section className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
        {paperMethods.map((method) => (
          <MethodCard key={method.id} method={method} locale={locale} />
        ))}
      </section>
    </div>
  )
}
