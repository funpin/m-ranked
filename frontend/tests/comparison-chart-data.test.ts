import assert from "node:assert/strict";
import test from "node:test";
import { comparisonPointSegments } from "../lib/comparison-chart-data";
import { formatPercentage } from "../lib/format";
import type { ComparisonPoint } from "../lib/types";

function point(hourOffset: number, value: number | null): ComparisonPoint {
  return { hourOffset, value, sampleSize: value === null ? 0 : 2, coverage: 1, quality: "exact" };
}

test("comparison chart does not bridge null or missing hourly points", () => {
  const segments = comparisonPointSegments([
    point(1, 10),
    point(2, 12),
    point(3, null),
    point(4, 14),
    point(6, 16),
  ]);

  assert.deepEqual(
    segments.map((segment) => segment.map(({ hourOffset }) => hourOffset)),
    [[1, 2], [4], [6]],
  );
});

test("engagement percentages keep the legacy two-decimal presentation", () => {
  assert.equal(formatPercentage(12.345), "12,35%");
  assert.equal(formatPercentage(null), "—");
});
