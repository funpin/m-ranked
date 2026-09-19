import type { CollectorCoverage, CollectorGap } from "./types";

export type IntervalCoverage =
  | { kind: "unknown" }
  | { kind: "covered" }
  | { kind: "gap"; gaps: number; missingSeconds: number };

function instant(value: string) {
  return Date.parse(value);
}

/** Only account-cycle gaps that overlap the requested wall-clock range. */
export function collectorGapsInRange(
  coverage: CollectorCoverage,
  from: string | number,
  to: string | number,
): CollectorGap[] {
  const low = typeof from === "number" ? from : instant(from);
  const high = typeof to === "number" ? to : instant(to);
  if (!Number.isFinite(low) || !Number.isFinite(high) || high <= low) return [];
  return coverage.gaps.filter((gap) => instant(gap.to) > low && instant(gap.from) < high);
}

/** Classifies one sparse-metric interval using the independent account run journal. */
export function collectorIntervalCoverage(
  coverage: CollectorCoverage,
  from: string,
  to: string,
): IntervalCoverage {
  const low = instant(from);
  const high = instant(to);
  const available = coverage.availableFrom ? instant(coverage.availableFrom) : Number.NaN;
  const through = instant(coverage.through);
  if (!Number.isFinite(low) || !Number.isFinite(high) || high <= low
      || !Number.isFinite(available) || low < available || high > through) {
    return { kind: "unknown" };
  }
  const gaps = collectorGapsInRange(coverage, low, high);
  if (!gaps.length) return { kind: "covered" };
  const missingSeconds = gaps.reduce((total, gap) => {
    const overlapFrom = Math.max(low, instant(gap.from));
    const overlapTo = Math.min(high, instant(gap.to));
    return total + Math.max(0, (overlapTo - overlapFrom) / 1000);
  }, 0);
  return { kind: "gap", gaps: gaps.length, missingSeconds };
}
