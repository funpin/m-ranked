import assert from "node:assert/strict";
import test from "node:test";
import { figureComparison } from "../lib/finding-figure";

test("comparison names how far the account is from typical in the finding's direction", () => {
  assert.equal(figureComparison({ value: 1.36, typical: 0.2, unit: "times", label: "", direction: "higher" }), "в 6,8 раза выше");
  assert.equal(figureComparison({ value: 0.05, typical: 0.4, unit: "decimal", label: "", direction: "lower" }), "в 8,0 раза ниже");
  assert.equal(figureComparison({ value: 1.1, typical: 1, unit: "times", label: "", direction: "higher" }), null);
});

test("a spread of zero is not divided by: it is said to be at the level of chance", () => {
  // ЮЗГУ в MAX: разброс сверх случайного 0 при типичных 0,29 — не «в 291 раз ниже».
  assert.equal(figureComparison({ value: 0, typical: 0.29, unit: "decimal", label: "", direction: "lower" }),
    "не больше случайного");
});

test("shares are compared as a ratio, not in percentage points", () => {
  assert.equal(figureComparison({ value: 0.5, typical: 0.06, unit: "percent", label: "постов в волнах реакций", direction: "higher" }),
    "в 8,3 раза чаще");
  assert.equal(figureComparison({ value: 0.35, typical: 0, unit: "percent", label: "постов на уровне 3", direction: "higher" }),
    "у типичного — почти нет");
  assert.equal(figureComparison({ value: 0.12, typical: 0.1, unit: "percent", label: "постов на уровне 3", direction: "higher" }), null);
});
