import { legacyNumber } from "./format";
import type { HistorySnapshot } from "./types";

export const historyMetrics = [
  { key: "reactions", delta: "deltaReactions", label: "Реакции", icon: "♥", color: "#16a085" },
  { key: "views", delta: "deltaViews", label: "Просмотры", icon: "👁", color: "#0868df" },
  { key: "comments", delta: "deltaComments", label: "Комментарии", icon: "💬", color: "#a86200" },
  { key: "shares", delta: "deltaShares", label: "Репосты", icon: "↗", color: "#7857c7" },
] as const;
export type HistoryMetric = typeof historyMetrics[number];

export function availableHistoryMetrics(rows: readonly HistorySnapshot[]) {
  return historyMetrics.filter(metric => rows.some(row => row[metric.key].value !== null || row[metric.delta] !== null));
}

/** Views and reactions are observed on every supported platform, so the history
 *  table keeps their columns even while a publication has no values yet: an
 *  empty column reads as "not collected", a missing one reads as "not a metric
 *  here". The other metrics stay data-driven. */
const ALWAYS_TABULATED = ["reactions", "views"] as const;
export function tabulatedHistoryMetrics(rows: readonly HistorySnapshot[]) {
  const available = new Set(availableHistoryMetrics(rows).map(metric => metric.key));
  return historyMetrics.filter(metric => available.has(metric.key)
    || (ALWAYS_TABULATED as readonly string[]).includes(metric.key));
}

export function metricLabel(metric: HistoryMetric, platform: string) {
  return metric.key === "reactions" && (platform === "vk" || platform === "rutube") ? "Лайки" : metric.label;
}

export function metricNoun(metric: HistoryMetric, platform: string) {
  return { reactions: platform === "vk" || platform === "rutube" ? "лайков" : "реакций",
    views: "просмотров", comments: "комментариев", shares: "репостов" }[metric.key];
}

/** A sampled chart point keeps the delta of its original observation. */
export function historyMetricValue(row: HistorySnapshot, metric: HistoryMetric, delta: boolean) {
  return delta ? row[metric.delta] : row[metric.key].value;
}

export function historyMetricTooltip(row: HistorySnapshot, metric: HistoryMetric, platform: string, delta: boolean) {
  const value = historyMetricValue(row, metric, delta);
  const signed = delta && value !== null && value >= 0 ? "+" : "";
  return `${delta ? "Прирост" : "Всего"} ${metricNoun(metric, platform)}: ${signed}${legacyNumber(value)}`;
}

export function historyRatioTooltip(row: HistorySnapshot, platform: string) {
  const views = row.views.value, reactions = row.reactions.value;
  if (views === null || views <= 0 || reactions === null) return "";
  return `${metricLabel(historyMetrics[0], platform)} / просмотры: ${(reactions * 100 / views).toFixed(2)}%`;
}
