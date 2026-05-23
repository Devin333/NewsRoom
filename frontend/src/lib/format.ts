export function cn(...classes: Array<string | false | null | undefined>) {
  return classes.filter(Boolean).join(" ");
}

export function formatDate(value?: string) {
  if (!value) {
    return "无";
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  return new Intl.DateTimeFormat("zh-CN", {
    month: "short",
    day: "numeric",
    year: "numeric",
  }).format(date);
}

export function formatDateTime(value?: string) {
  if (!value) {
    return "无";
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  return new Intl.DateTimeFormat("zh-CN", {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
}

export function formatRelativeTime(value?: string, now: Date = new Date()) {
  if (!value) {
    return "无";
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  const seconds = Math.round((date.getTime() - now.getTime()) / 1000);
  const absSeconds = Math.abs(seconds);
  const units: Array<[Intl.RelativeTimeFormatUnit, number]> = [
    ["year", 60 * 60 * 24 * 365],
    ["month", 60 * 60 * 24 * 30],
    ["week", 60 * 60 * 24 * 7],
    ["day", 60 * 60 * 24],
    ["hour", 60 * 60],
    ["minute", 60],
    ["second", 1],
  ];
  const [unit, unitSeconds] = units.find(([, size]) => absSeconds >= size) ?? ["second", 1];
  return new Intl.RelativeTimeFormat("zh-CN", { numeric: "auto" }).format(Math.round(seconds / unitSeconds), unit);
}

export function formatNumber(value?: number) {
  if (value === undefined || Number.isNaN(value)) {
    return "无";
  }
  return new Intl.NumberFormat("zh-CN").format(value);
}

export function formatPercent(value?: number) {
  if (value === undefined || Number.isNaN(value)) {
    return "无";
  }
  const normalized = value <= 1 ? value * 100 : value;
  return `${Math.round(normalized)}%`;
}

export function formatDurationMs(value?: number) {
  if (value === undefined || Number.isNaN(value)) {
    return "无";
  }
  if (value < 1000) {
    return `${Math.round(value)} 毫秒`;
  }
  const seconds = value / 1000;
  if (seconds < 60) {
    return `${trimNumber(seconds)} 秒`;
  }
  const minutes = Math.floor(seconds / 60);
  const remainingSeconds = Math.round(seconds % 60);
  if (minutes < 60) {
    return remainingSeconds ? `${minutes}分 ${remainingSeconds}秒` : `${minutes}分`;
  }
  const hours = Math.floor(minutes / 60);
  const remainingMinutes = minutes % 60;
  return remainingMinutes ? `${hours}小时 ${remainingMinutes}分` : `${hours}小时`;
}

export function formatBytes(value?: number) {
  if (value === undefined || Number.isNaN(value)) {
    return "无";
  }
  if (value === 0) {
    return "0 B";
  }
  const units = ["B", "KB", "MB", "GB", "TB"];
  const exponent = Math.min(Math.floor(Math.log(Math.abs(value)) / Math.log(1024)), units.length - 1);
  const amount = value / 1024 ** exponent;
  const digits = amount >= 10 || exponent === 0 ? 0 : 1;
  return `${amount.toFixed(digits)} ${units[exponent]}`;
}

export function formatScore(value?: number) {
  if (value === undefined) {
    return "无";
  }
  if (value <= 1) {
    return `${Math.round(value * 100)}%`;
  }
  return `${Math.round(value)}%`;
}

export function titleCase(value: string) {
  const mapped = labelMap[value];
  if (mapped) {
    return mapped;
  }
  return value
    .split("_")
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");
}

const labelMap: Record<string, string> = {
  agent_run: "智能体运行",
  arxiv: "arXiv",
  atom: "Atom",
  approved: "已批准",
  citationQuality: "引用质量",
  collected: "已采集",
  custom: "自定义",
  devto: "dev.to",
  daily: "日报",
  dataset: "数据集",
  degraded: "降级",
  disabled: "已停用",
  duplicateRisk: "重复风险",
  emerging: "新兴",
  evidence: "证据",
  evidenceCompleteness: "证据完整性",
  experimental: "实验",
  falling: "下降",
  factConsistency: "事实一致性",
  failed: "失败",
  framework: "框架",
  generated: "已生成",
  github: "GitHub",
  hackernews: "Hacker News",
  healthy: "健康",
  high: "高",
  html: "HTML",
  humanReviewRequired: "需要人工复核",
  json: "JSON",
  local: "本地",
  log: "日志",
  low: "低",
  markdown: "Markdown",
  mature: "成熟",
  media: "媒体",
  medium: "中",
  manual: "手动",
  memory: "记忆",
  method: "方法",
  news: "新闻",
  needs_changes: "需要修改",
  needs_review: "需要复核",
  objects: "对象",
  official_blog: "官方博客",
  paper: "论文",
  passed: "通过",
  pending: "待处理",
  practice: "实践",
  reddit: "Reddit",
  report: "报告",
  reported: "已报道",
  repo: "仓库",
  review_required: "需要复核",
  rising: "上升",
  rss: "RSS",
  stackoverflow: "StackOverflow",
  running: "运行中",
  source: "数据源",
  source_health: "数据源健康",
  sourceCoverage: "来源覆盖",
  stable: "稳定",
  summaryCompleteness: "摘要完整性",
  titleQuality: "标题质量",
  tech: "技术",
  topic: "主题",
  weekly: "周报",
  warning: "警告",
  web_page: "网页",
};

function trimNumber(value: number) {
  return value.toFixed(value >= 10 ? 0 : 1).replace(/\.0$/, "");
}
