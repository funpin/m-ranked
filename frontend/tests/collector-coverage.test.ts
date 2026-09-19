import assert from "node:assert/strict";
import test from "node:test";
import { collectorGapsInRange, collectorIntervalCoverage } from "../lib/collector-coverage";
import type { CollectorCoverage } from "../lib/types";

const coverage: CollectorCoverage = {
  availableFrom: "2026-09-18T18:00:00Z",
  through: "2026-09-19T04:00:00Z",
  expectedIntervalSeconds: 300,
  successfulPolls: 100,
  failedPolls: 1,
  gaps: [{
    from: "2026-09-19T02:55:00Z",
    to: "2026-09-19T03:07:00Z",
    missingSeconds: 720,
  }],
};

test("sparse saved points are covered when account cycles continued", () => {
  assert.deepEqual(collectorIntervalCoverage(
    coverage,
    "2026-09-18T20:45:39Z",
    "2026-09-19T02:40:00Z",
  ), { kind: "covered" });
});

test("a real collector interruption is reported inside a sparse interval", () => {
  assert.deepEqual(collectorIntervalCoverage(
    coverage,
    "2026-09-18T20:45:39Z",
    "2026-09-19T03:07:35Z",
  ), { kind: "gap", gaps: 1, missingSeconds: 720 });
});

test("history before the account run journal stays unknown", () => {
  assert.deepEqual(collectorIntervalCoverage(
    coverage,
    "2026-09-18T17:00:00Z",
    "2026-09-18T19:00:00Z",
  ), { kind: "unknown" });
});

test("chart gaps are selected by overlap rather than saved-point spacing", () => {
  assert.equal(collectorGapsInRange(
    coverage,
    "2026-09-19T02:50:00Z",
    "2026-09-19T03:00:00Z",
  ).length, 1);
  assert.equal(collectorGapsInRange(
    coverage,
    "2026-09-19T01:00:00Z",
    "2026-09-19T02:00:00Z",
  ).length, 0);
});
