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

test("evidence names every quality rank in words and never shows a raw code", () => {
  const base = { asOf: "2026-08-01T12:00:00Z", datasetRevision: 7, value: 5, sampleSize: 3, coverage: 1 };
  assert.match(metricEvidence({ ...base, quality: "unknown" })!, /качество: точность не подтверждена/);
  assert.match(metricEvidence({ ...base, quality: "suspected_reset" })!, /качество: возможен сброс счётчика/);
  assert.match(metricEvidence({ ...base, quality: "something_new" })!, /качество: качество не указано/);
  assert.doesNotMatch(metricEvidence({ ...base, quality: "unknown" })!, /unknown/);
});
