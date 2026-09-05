import { metricNumber } from "./params";
import type { ComparisonPoint } from "./types";

export interface NumericComparisonPoint extends ComparisonPoint {
  numericValue: number;
}

/**
 * Keeps missing hourly values as visible gaps instead of drawing a line across
 * unavailable denominator/numerator observations.
 */
export function comparisonPointSegments(
  points: readonly ComparisonPoint[],
): NumericComparisonPoint[][] {
  const segments: NumericComparisonPoint[][] = [];
  let current: NumericComparisonPoint[] | null = null;
  let previousHour: number | null = null;

  for (const point of points) {
    const numericValue = metricNumber(point.value);
    if (numericValue === null) {
      current = null;
      previousHour = null;
      continue;
    }
    if (current === null || previousHour === null || point.hourOffset !== previousHour + 1) {
      current = [];
      segments.push(current);
    }
    current.push({ ...point, numericValue });
    previousHour = point.hourOffset;
  }
  return segments;
}
