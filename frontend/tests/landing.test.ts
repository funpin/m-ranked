import assert from "node:assert/strict";
import test from "node:test";
import {
  CORRIDOR_SHAPES, corridorBand, corridorShapePath, countWithUnit, formatStat, heroCurves, landingDashboard,
  platformsFromSummary, summaryDate,
} from "../lib/landing";
import type { Dashboard } from "../lib/compare-dashboard";

test("крупные числа сводки сокращаются только от миллиона", () => {
  assert.equal(formatStat(84), "84");
  assert.equal(formatStat(73_879), "73 879");
  assert.equal(formatStat(13_204_551), "13,2 млн");
  assert.equal(formatStat(2_000_000_000), "2 млрд");
});

test("число аккаунтов согласуется с единицей площадки", () => {
  assert.equal(countWithUnit(1, "канал"), "1 канал");
  assert.equal(countWithUnit(83, "канал"), "83 канала");
  assert.equal(countWithUnit(84, "сообщество"), "84 сообщества");
  assert.equal(countWithUnit(11, "сообщество"), "11 сообществ");
  assert.equal(countWithUnit(5, "неизвестная"), "5 аккаунтов");
});

test("площадки берутся из сводки: новая появляется без правки главной", () => {
  const platforms = platformsFromSummary({ accountsByPlatform: { telegram: 83, vk: 84, ok: 3, max: 83, rutube: 0 } });
  assert.deepEqual(platforms.map((item) => item.platform), ["vk", "max", "telegram", "ok"]);
  assert.deepEqual(platforms[0], { platform: "vk", accounts: 84 });
});

test("дата пересчёта — по Москве и без «г.»", () => {
  assert.equal(summaryDate("2026-09-25T22:30:00Z"), "26 сентября 2026");
});

test("фон первого экрана одинаков при каждой отрисовке", () => {
  const first = heroCurves();
  assert.deepEqual(first, heroCurves());
  assert.ok(first.some((curve) => curve.lead && curve.marks.length > 3));
  assert.ok(first.every((curve) => curve.d.startsWith("M") && !curve.d.includes("NaN")));
});

test("формы коридора анимируются друг в друга: одинаковое число точек", () => {
  const counts = CORRIDOR_SHAPES.map((shape) => corridorShapePath(shape.id).split(/[ML]/).length);
  assert.equal(new Set(counts).size, 1);
  const band = corridorBand();
  assert.ok(band.area.endsWith("Z") && Number.isFinite(band.labelY));
});

test("в разметку главной не уходят данные, которые она не рисует", () => {
  const data = {
    period: "30d", hours: [1, 24], datasetRevision: 1, asOf: "2026-09-26T00:00:00Z", institutions: [],
    stats: [{ institutionId: null, platform: "vk" }, { institutionId: "a", platform: "vk" }],
    curves: [{ institutionId: null, platform: "vk", samples: [1, 1], views: [1, 2], reactions: [0, 1] }],
    daily: [{ day: "2026-09-25" }], timing: [{ weekday: 1 }], types: [{ type: "text" }],
  } as unknown as Dashboard;
  const pruned = landingDashboard(data);
  assert.equal(pruned.stats.length, 1);
  assert.deepEqual(pruned.curves[0]!.reactions, []);
  assert.deepEqual(pruned.curves[0]!.views, [1, 2]);
  assert.deepEqual([pruned.timing, pruned.types], [[], []]);
  assert.equal(pruned.daily.length, 1);
});
