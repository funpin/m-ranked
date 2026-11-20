import { test } from "node:test";
import assert from "node:assert/strict";
import { hasActual, isIncomplete, monthLabel, monthShift, normalizeCategory, normalizeMonth, normalizeView, placeGap, rankDelta, rankLabel, rowsFor, scatterPoints, signed, sourceNote, statusLine, stripPosition, viewScore } from "../lib/rating";
import type { RatingForecastCell, RatingForecastRow } from "../lib/types";

const cell = (rank: number, extra: Partial<RatingForecastCell> = {}): RatingForecastCell => ({
  score: 60, rank, rankBest: rank, rankWorst: rank, baseRank: null, source: "formula", actualRank: null, actualScore: null, ...extra,
});
const row = (name: string, social: number, vk: number, actual: number | null = null): RatingForecastRow => ({
  institutionId: "00000000-0000-0000-0000-000000000001", legacyId: 1, name, shortName: null, baseConsolidatedRank: null,
  categories: { social: cell(social, { actualRank: actual }), max: cell(1), vk: cell(vk), rutube: cell(1) },
});

test("category and month parameters fall back safely", () => {
  assert.equal(normalizeCategory("vk"), "vk");
  assert.equal(normalizeCategory(["rutube", "vk"]), "rutube");
  assert.equal(normalizeCategory("telegram"), "social");
  assert.equal(normalizeMonth("2026-10"), "2026-10");
  assert.equal(normalizeMonth("2026-13"), null);
  assert.equal(normalizeMonth(undefined), null);
});

test("rank label shows the range only when it is wider than the rank", () => {
  assert.equal(rankLabel(cell(8)), "8");
  assert.equal(rankLabel(cell(8, { rankBest: 5, rankWorst: 14 })), "8 (5–14)");
});

test("delta is positive when the institution climbs", () => {
  assert.equal(rankDelta(cell(8, { baseRank: 11 })), 3);
  assert.equal(rankDelta(cell(8)), null);
});

test("rows are ordered by the selected category", () => {
  const rows = [row("А", 2, 9), row("Б", 1, 3)];
  assert.deepEqual(rowsFor(rows, "social").map((item) => item.name), ["Б", "А"]);
  assert.deepEqual(rowsFor(rows, "vk").map((item) => item.name), ["Б", "А"]);
  assert.deepEqual(rowsFor([row("А", 2, 1), row("Б", 1, 3)], "vk").map((item) => item.name), ["А", "Б"]);
});

test("scatter keeps only rows with an actual place", () => {
  assert.deepEqual(scatterPoints([row("А", 2, 1, 4), row("Б", 1, 3)], "social"), [{ name: "А", predicted: 2, actual: 4 }]);
});

test("status line speaks plain Russian", () => {
  assert.equal(statusLine({ status: "running", asOf: "2026-10-15T22:10:00Z", early: false }), "Месяц не закончен, данные на 16.10");
  assert.equal(statusLine({ status: "running", asOf: "2026-11-02T22:10:00Z", early: true }),
    "Месяц не закончен, данные на 03.11 — слишком рано для уверенной оценки");
  assert.equal(statusLine({ status: "final", asOf: "2026-11-05T22:10:00Z", early: false }), "Итоговый прогноз: месяц закончен, официального списка ещё нет");
  assert.equal(statusLine({ status: "published", asOf: "2026-11-12T22:10:00Z", early: false }), "Опубликовано — прогноз против факта");
  assert.equal(statusLine({ status: "retrospective", asOf: "2026-10-16T22:10:00Z", early: false }),
    "Ретроспективный расчёт, не прогноз до публикации");
  assert.equal(hasActual({ status: "retrospective" }), true);
  assert.equal(hasActual({ status: "final" }), false);
});

test("month switcher reads as a Russian month name", () => {
  assert.equal(monthLabel("2026-10"), "Октябрь 2026");
  assert.equal(monthLabel("2027-01"), "Январь 2027");
});

test("place strip positions stay inside the scale", () => {
  assert.deepEqual(stripPosition(1, 233), 0);
  assert.deepEqual(stripPosition(233, 233), 100);
  assert.equal(stripPosition(300, 233), 100);
});

test("source notes explain every non-formula cell", () => {
  assert.equal(sourceNote(cell(5, { source: "formula" }), "Сентябрь 2026"), null);
  assert.equal(sourceNote(cell(5, { source: "fallback" }), "Сентябрь 2026"), "нет полных данных — взят балл за сентябрь 2026");
  assert.equal(sourceNote(cell(5, { source: "source_zero" }), "Сентябрь 2026"),
    "рейтинг не учитывает этот канал: 0 два месяца подряд");
});

test("view parameter falls back to the forecast", () => {
  assert.equal(normalizeView("fact"), "fact");
  assert.equal(normalizeView(["fact", "forecast"]), "fact");
  assert.equal(normalizeView("other"), "forecast");
  assert.equal(normalizeView(undefined), "forecast");
});

test("Δ compares with last month: our forecast or the actual place", () => {
  const value = cell(8, { baseRank: 11, actualRank: 10 });
  assert.equal(monthShift(value, "forecast"), 3);
  assert.equal(monthShift(value, "fact"), 1);
  assert.equal(monthShift(cell(8, { actualRank: 10 }), "fact"), null);
  assert.equal(monthShift(cell(8, { baseRank: 11 }), "fact"), null);
});

test("± is plus when the other place is higher", () => {
  // Прогноз 12, факт 10: факт на 2 места выше прогноза, прогноз на 2 ниже факта.
  const value = cell(12, { actualRank: 10 });
  assert.equal(placeGap(value, "forecast"), 2);
  assert.equal(placeGap(value, "fact"), -2);
  assert.equal(placeGap(cell(12), "forecast"), null);
  assert.equal(signed(2), "+2");
  assert.equal(signed(-2), "−2");
  assert.equal(signed(0), "0");
});

test("rows follow the actual place in the fact view, rows without one go last", () => {
  const rows = [row("А", 1, 1, 3), row("Б", 2, 1, 1), row("В", 3, 1)];
  assert.deepEqual(rowsFor(rows, "social", "fact").map((item) => item.name), ["Б", "А", "В"]);
  assert.deepEqual(rowsFor(rows, "social", "forecast").map((item) => item.name), ["А", "Б", "В"]);
});

test("score follows the view", () => {
  assert.equal(viewScore(cell(5, { score: 61.2, actualScore: 58.4 }), "forecast"), 61.2);
  assert.equal(viewScore(cell(5, { score: 61.2, actualScore: 58.4 }), "fact"), 58.4);
  assert.equal(viewScore(cell(5, { score: 61.2 }), "fact"), null);
});

test("incomplete cells are marked, regular formula and missing accounts are not", () => {
  assert.equal(isIncomplete(cell(5, { source: "fallback" })), true);
  assert.equal(isIncomplete(cell(5, { source: "partial" })), true);
  assert.equal(isIncomplete(cell(5, { source: "source_zero" })), true);
  assert.equal(isIncomplete(cell(5, { source: "formula" })), false);
  assert.equal(isIncomplete(cell(5, { source: "no_account" })), false);
});
