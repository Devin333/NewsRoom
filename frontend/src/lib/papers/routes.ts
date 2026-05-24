import type { PaperModuleRoute } from "@/lib/papers/types"

export const papersRoutes = {
  trending: "/papers",
  tasks: "/papers/tasks",
  taskDetail: (slug: string) => `/papers/tasks/${slug}` as PaperModuleRoute,
  methods: "/papers/methods",
  methodDetail: (slug: string) => `/papers/methods/${slug}` as PaperModuleRoute
} satisfies Record<string, PaperModuleRoute | ((slug: string) => PaperModuleRoute)>

export const papersDropdownItems = [
  {
    labelKey: "trendingPapers",
    descriptionKey: "dropdownTrendingDescription",
    href: papersRoutes.trending
  },
  {
    labelKey: "tasks",
    descriptionKey: "dropdownTasksDescription",
    href: papersRoutes.tasks
  },
  {
    labelKey: "methods",
    descriptionKey: "dropdownMethodsDescription",
    href: papersRoutes.methods
  }
] as const
