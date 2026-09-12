import assert from "node:assert/strict";
import test from "node:test";
import { comparisonEvidence, comparisonRows, seriesKey } from "../lib/comparison-chart-data";
import { formatPercentage } from "../lib/format";
import type { ComparisonPoint, ComparisonSeries } from "../lib/types";

function point(hourOffset: number, value: number | null): ComparisonPoint {
  return { hourOffset, value, sampleSize: value === null ? 0 : 2, coverage: 1, quality: "exact" };
}

function series(points: ComparisonPoint[]): ComparisonSeries {
  return {
    selectionId: "a", selectionLabel: "Ряд", points,
    engagementPoints: [], primaryCohortSize: 3, engagementCohortSize: 3,
  } as unknown as ComparisonSeries;
}

test("comparison chart does not bridge null or missing hourly points", () => {
  const rows = comparisonRows([series([
    point(1, 10),
    point(2, 12),
    point(3, null),
    point(4, 14),
    point(6, 16),
  ])], 6);
  const key = seriesKey("a");

  assert.deepEqual(rows.map((row) => row.hour), [0, 1, 2, 3, 4, 5, 6]);
  // Hour 3 carries an explicit null, hours 0 and 5 were never reported; both
  // break the line instead of joining the values on either side.
  assert.deepEqual(rows.map((row) => row[key]), [null, 10, 12, null, 14, null, 16]);
});

test("every selected series gets a column on every row", () => {
  const rows = comparisonRows([
    { ...series([point(0, 1)]), selectionId: "a" },
    { ...series([point(1, 2)]), selectionId: "b" },
  ], 1);

  for (const row of rows) {
    assert.ok(seriesKey("a") in row);
    assert.ok(seriesKey("b") in row);
  }
});

test("evidence keeps the sample size reported for each hour", () => {
  const evidence = comparisonEvidence([series([point(2, 12)])]);
  assert.equal(evidence.get("a")?.get(2)?.sampleSize, 2);
  assert.equal(evidence.get("a")?.get(3), undefined);
});

test("engagement percentages keep the legacy two-decimal presentation", () => {
  assert.equal(formatPercentage(12.345), "12,35%");
  assert.equal(formatPercentage(null), "—");
});
