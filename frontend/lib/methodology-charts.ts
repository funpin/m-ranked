/** Рисунки, которые статьи методологии вставляют через <Figure chart="…" />. */
export const CHART_NAMES = [
  "decay", "strengths", "levels", "families", "schedule", "linear-feed", "late-spike", "gap-growth", "catch-up",
  "reactions-before-views", "reactions-exceed-views", "synchronous-rise", "burst-plateau", "bounded-burst", "erv",
  "mature-reference", "late-engagement", "tail-cohort", "tail-histogram", "tail-statuses", "tail-sensitivity",
] as const;

export type ChartName = (typeof CHART_NAMES)[number];
