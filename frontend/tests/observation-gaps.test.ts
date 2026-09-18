import assert from "node:assert/strict";
import test from "node:test";
import { expectedObservationMinutes, observationGaps } from "../lib/observation-gaps";
import type { HistorySnapshot } from "../lib/types";

function sample(minute: number, ageHours: number): HistorySnapshot {
  return {
    observedAt: new Date(Date.UTC(2026, 8, 18, 0, minute)).toISOString(),
    ageHours,
  } as HistorySnapshot;
}

test("ожидаемый шаг зависит от возраста поста и площадки", () => {
  assert.equal(expectedObservationMinutes("max", 10), 5);
  assert.equal(expectedObservationMinutes("max", 80), 30);
  assert.equal(expectedObservationMinutes("rutube", 10), 60);
  assert.equal(expectedObservationMinutes("rutube", 200), 360);
});

test("обычный 30-минутный шаг старого поста не считается пропуском", () => {
  assert.deepEqual(observationGaps([sample(0, 80), sample(30, 80.5)], "max"), []);
});

test("заштриховывается только часть после ожидаемого замера", () => {
  const [gap] = observationGaps([sample(0, 80), sample(60, 81)], "max");
  assert.ok(gap);
  assert.equal(gap.from - gap.actualFrom, 30 * 60_000);
  assert.equal(gap.missingSeconds, 30 * 60);
});

test("часовой шаг Rutube не помечается как авария", () => {
  assert.deepEqual(observationGaps([sample(0, 10), sample(60, 11)], "rutube"), []);
});
