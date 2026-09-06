import assert from "node:assert/strict";
import test from "node:test";
import { metricEvidence } from "../lib/metric-evidence";

test("per-metric evidence preserves distinct candidates and measured zero without borrowing metadata", () => {
  const common = { asOf: "2026-08-01T12:00:00Z", datasetRevision: 7, quality: "exact" };
  const views = metricEvidence({ ...common, value: 20, sampleSize: 10, coverage: 1 });
  const reactions = metricEvidence({ ...common, value: 0, sampleSize: 1, coverage: 0.1 });
  assert.match(views!, /Выборка: 10/);
  assert.match(reactions!, /Выборка: 1;/);
  assert.match(reactions!, /10/);
  assert.equal(metricEvidence(undefined), undefined);
});
