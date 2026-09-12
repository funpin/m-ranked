import { metricNumber } from "./params";
import type { ComparisonPoint, ComparisonSeries } from "./types";

/** One row per hour on the axis; one column per selected series. */
export type ComparisonRow = Record<string, number | null> & { hour: number };

/** Column key for a series. Recharts addresses data by key, not by index. */
export const seriesKey = (selectionId: string) => `s${selectionId}`;

/**
 * Builds the plot rows. An hour a series has no usable value for stays null,
 * so the line breaks there rather than being drawn across an unavailable
 * numerator or denominator. Hours missing from the response break the line for
 * the same reason: the series simply has no column value at that row.
 */
export function comparisonRows(
  series: readonly ComparisonSeries[],
  maximumHour: number,
): ComparisonRow[] {
  const byHour = new Map<number, ComparisonRow>();
  for (let hour = 0; hour <= maximumHour; hour++) {
    byHour.set(hour, { hour } as ComparisonRow);
  }
  for (const item of series) {
    const key = seriesKey(item.selectionId);
    for (const point of item.points) {
      const row = byHour.get(point.hourOffset);
      if (!row) continue;
      row[key] = metricNumber(point.value);
    }
  }
  for (const row of byHour.values()) {
    for (const item of series) {
      const key = seriesKey(item.selectionId);
      if (row[key] === undefined) row[key] = null;
    }
  }
  return [...byHour.values()];
}

/**
 * Sample size and coverage per series per hour, which the tooltip and the
 * keyboard reading report alongside the value.
 */
export function comparisonEvidence(series: readonly ComparisonSeries[]) {
  const evidence = new Map<string, Map<number, ComparisonPoint>>();
  for (const item of series) {
    const hours = new Map<number, ComparisonPoint>();
    for (const point of item.points) hours.set(point.hourOffset, point);
    evidence.set(item.selectionId, hours);
  }
  return evidence;
}
