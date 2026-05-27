import type { Paper, TaskRef } from "@/lib/papers/types"

export type PaperPortalMetrics = {
  paperCount: number
  taskCount: number
  repositoryCount: number
}

type TaskAggregate = {
  ref: TaskRef
  paperIds: Set<string>
  score: number
}

export function buildPaperPortalMetrics(papers: Paper[], totalCount?: number): PaperPortalMetrics {
  const publicPapers = publishedPapers(papers)
  return {
    paperCount: Number.isFinite(totalCount) && typeof totalCount === "number" ? totalCount : publicPapers.length,
    taskCount: uniqueTaskSlugs(publicPapers).size,
    repositoryCount: uniqueRepositoryKeys(publicPapers).size
  }
}

export function deriveTopPaperDomains(papers: Paper[], limit = 4): TaskRef[] {
  return taskAggregates(papers)
    .sort((left, right) => {
      const countDelta = right.paperIds.size - left.paperIds.size
      if (countDelta) return countDelta
      const scoreDelta = right.score - left.score
      if (scoreDelta) return scoreDelta
      return left.ref.name.localeCompare(right.ref.name)
    })
    .slice(0, limit)
    .map((item) => item.ref)
}

export function deriveTrendingPaperDomains(papers: Paper[], limit = 4, now = new Date()): TaskRef[] {
  return taskAggregates(papers, now)
    .sort((left, right) => {
      const scoreDelta = right.score - left.score
      if (scoreDelta) return scoreDelta
      const countDelta = right.paperIds.size - left.paperIds.size
      if (countDelta) return countDelta
      return left.ref.name.localeCompare(right.ref.name)
    })
    .slice(0, limit)
    .map((item) => item.ref)
}

export function countUniqueRepositories(papers: Paper[]) {
  return uniqueRepositoryKeys(publishedPapers(papers)).size
}

function taskAggregates(papers: Paper[], now = new Date()) {
  const records = new Map<string, TaskAggregate>()
  for (const paper of publishedPapers(papers)) {
    const seenTaskSlugs = new Set<string>()
    for (const task of paper.taskRefs ?? []) {
      if (!task.slug || seenTaskSlugs.has(task.slug)) {
        continue
      }
      seenTaskSlugs.add(task.slug)
      const record = records.get(task.slug) ?? {
        ref: task,
        paperIds: new Set<string>(),
        score: 0
      }
      record.ref = mergeTaskRef(record.ref, task)
      record.paperIds.add(paper.id)
      record.score += paperTrendScore(paper, now)
      records.set(task.slug, record)
    }
  }
  return [...records.values()]
}

function uniqueTaskSlugs(papers: Paper[]) {
  const slugs = new Set<string>()
  for (const paper of papers) {
    for (const task of paper.taskRefs ?? []) {
      if (task.slug) {
        slugs.add(task.slug)
      }
    }
  }
  return slugs
}

function uniqueRepositoryKeys(papers: Paper[]) {
  const keys = new Set<string>()
  for (const paper of papers) {
    addRepositoryKey(keys, paper.repoUrl)
    for (const implementation of paper.implementations ?? []) {
      addRepositoryKey(keys, implementation.repoUrl)
    }
  }
  return keys
}

function addRepositoryKey(keys: Set<string>, value?: string) {
  const key = repositoryKey(value)
  if (key) {
    keys.add(key)
  }
}

function repositoryKey(value?: string) {
  if (!value) {
    return null
  }
  try {
    const url = new URL(value.trim().replace(/^http:\/\//i, "https://"))
    const host = url.hostname.toLowerCase().replace(/^www\./, "")
    const parts = url.pathname
      .split("/")
      .map((part) => part.trim())
      .filter(Boolean)
    if (!host || !parts.length) {
      return null
    }
    if (host === "github.com" && parts.length >= 2) {
      return `${host}/${parts[0].toLowerCase()}/${parts[1].replace(/\.git$/i, "").toLowerCase()}`
    }
    return `${host}/${parts.join("/").replace(/\/$/i, "").toLowerCase()}`
  } catch {
    return value.trim().toLowerCase().replace(/\.git$/i, "") || null
  }
}

function publishedPapers(papers: Paper[]) {
  return papers.filter((paper) => paper.isPublished !== false)
}

function paperTrendScore(paper: Paper, now: Date) {
  const publishedTime = new Date(paper.publishedAt).getTime()
  const ageDays = Number.isFinite(publishedTime) ? Math.max(0, (now.getTime() - publishedTime) / 86_400_000) : 90
  const recency = Math.max(0, 45 - ageDays) / 45
  const github = Math.sqrt(Math.max(0, paper.githubStars ?? 0))
  const citations = Math.sqrt(Math.max(0, paper.citationCount ?? 0))
  const momentum = Math.max(0, paper.githubMomentum ?? 0)
  const heat = Math.max(0, paper.newsroomHeatScore ?? 0)
  return 1 + recency * 20 + github + citations * 1.5 + momentum * 10 + heat / 10
}

function mergeTaskRef(existing: TaskRef, next: TaskRef): TaskRef {
  return {
    ...existing,
    ...Object.fromEntries(
      Object.entries(next).filter(([, value]) => value !== undefined && value !== null && value !== "")
    )
  }
}
