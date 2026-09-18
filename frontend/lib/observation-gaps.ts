import { duration } from "@/lib/format";
import type { HistorySnapshot, Platform } from "@/lib/types";

export type ObservationGap = {
  from: number;
  to: number;
  actualFrom: number;
  actualTo: number;
  missingSeconds: number;
  expectedMinutes: number;
  label: string;
};

/** Collector cadence at a publication's current age. */
export function expectedObservationMinutes(platform: Exclude<Platform, "all">, ageHours: number) {
  if (platform === "rutube") {
    if (ageHours < 72) return 60;
    if (ageHours < 168) return 180;
    if (ageHours < 336) return 360;
    return 720;
  }
  if (ageHours < 24) return 5;
  if (ageHours < 72) return 15;
  if (ageHours < 168) return 30;
  return 60;
}

/** Finds missed scheduled observations and shades only their overdue part. */
export function observationGaps(rows: HistorySnapshot[], platform: Exclude<Platform, "all">) {
  const gaps: ObservationGap[] = [];
  for (let index = 1; index < rows.length; index++) {
    const previous = rows[index - 1]!;
    const current = rows[index]!;
    const actualFrom = Date.parse(previous.observedAt);
    const actualTo = Date.parse(current.observedAt);
    const expectedMinutes = expectedObservationMinutes(platform, previous.ageHours);
    const expectedMs = expectedMinutes * 60_000;
    const actualMs = actualTo - actualFrom;
    // Scheduler jitter must not turn a normal interval into a gap. Reaching
    // 1.75 cadences means a scheduled observation was effectively missed.
    if (!Number.isFinite(actualMs) || actualMs < expectedMs * 1.75) continue;
    const from = actualFrom + expectedMs;
    const missingSeconds = Math.max(0, (actualTo - from) / 1000);
    gaps.push({
      from, to: actualTo, actualFrom, actualTo, missingSeconds, expectedMinutes,
      label: `нет данных сверх шага ${duration(missingSeconds)}`,
    });
  }
  return gaps;
}
