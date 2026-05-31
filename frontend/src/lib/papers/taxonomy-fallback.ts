import type { Paper, PaperMethod, PaperTask } from "@/lib/papers/types"

export function deriveTasksFromPapers(seedTasks: PaperTask[], papers: Paper[]): PaperTask[] {
  return seedTasks.map((task) => {
    const taskPapers = publishedPapers(papers).filter((paper) =>
      (paper.taskRefs ?? []).some((taskRef) => taskRef.slug === task.slug)
    )
    const methodSlugs = new Set<string>()
    const benchmarkKeys = new Set<string>()
    const implementationKeys = new Set<string>()

    for (const paper of taskPapers) {
      for (const method of paper.methodRefs ?? []) {
        if (method.slug) {
          methodSlugs.add(method.slug)
        }
      }
      for (const benchmark of paper.benchmarks ?? []) {
        benchmarkKeys.add(benchmark.id || benchmark.name)
      }
      addRepositoryKey(implementationKeys, paper.repoUrl)
      for (const implementation of paper.implementations ?? []) {
        addRepositoryKey(implementationKeys, implementation.repoUrl)
      }
    }

    return {
      ...task,
      paperCount: taskPapers.length,
      benchmarkCount: benchmarkKeys.size,
      methodCount: methodSlugs.size,
      latestPaperIds: latestPaperIds(taskPapers),
      implementationCount: implementationKeys.size
    }
  })
}

export function deriveMethodsFromPapers(seedMethods: PaperMethod[], papers: Paper[]): PaperMethod[] {
  return seedMethods.map((method) => {
    const methodPapers = publishedPapers(papers).filter((paper) =>
      (paper.methodRefs ?? []).some((methodRef) => methodRef.slug === method.slug)
    )
    const taskSlugs = new Set<string>()
    const implementationKeys = new Set<string>()

    for (const paper of methodPapers) {
      for (const task of paper.taskRefs ?? []) {
        if (task.slug) {
          taskSlugs.add(task.slug)
        }
      }
      addRepositoryKey(implementationKeys, paper.repoUrl)
      for (const implementation of paper.implementations ?? []) {
        addRepositoryKey(implementationKeys, implementation.repoUrl)
      }
    }

    return {
      ...method,
      paperCount: methodPapers.length,
      taskCount: taskSlugs.size,
      implementationCount: implementationKeys.size,
      representativePaperIds: latestPaperIds(methodPapers),
      relatedProjectIds: []
    }
  })
}

function latestPaperIds(papers: Paper[]) {
  return [...papers]
    .sort((left, right) => paperTime(right) - paperTime(left) || left.id.localeCompare(right.id))
    .map((paper) => paper.id)
}

function publishedPapers(papers: Paper[]) {
  return papers.filter((paper) => paper.isPublished !== false)
}

function paperTime(paper: Paper) {
  const time = new Date(paper.publishedAt).getTime()
  return Number.isFinite(time) ? time : 0
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
