import assert from "node:assert/strict";
import test from "node:test";
import {
  CORRIDOR_SHAPES, corridorBand, corridorCrowd, corridorShapePath, countWithUnit, formatStat, landingDashboard, sceneCurves,
  phoneSummary, platformsFromSummary,
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

test("модель первого экрана одинакова при каждой отрисовке и не выходит из сцены", () => {
  const curves = sceneCurves();
  assert.deepEqual(curves, sceneCurves());
  assert.ok(curves.some((curve) => curve.lead));
  for (const curve of curves) {
    for (const [x, y, z] of curve.points) {
      assert.ok(Number.isFinite(x + y + z));
      assert.ok(x >= -3.21 && x <= 3.21 && y >= 0 && y <= 2.41 && z >= -2.3 && z <= 2.3, `${x} ${y} ${z}`);
    }
    // Накопленное значение не убывает: это счётчик.
    assert.ok(curve.points.every((point, index) => index === 0 || point[1] >= curve.points[index - 1]![1]));
  }
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
  assert.deepEqual([pruned.curves, pruned.types, pruned.institutions], [[], [], []]);
  assert.deepEqual(pruned.timing, [{ weekday: 1 }]);
  assert.equal(pruned.daily.length, 1);
});

test("живые посты неровные, но не убывают и не выходят из обычного разброса", () => {
  const normal = CORRIDOR_SHAPES.find((shape) => shape.id === "normal")!;
  const typical = (t: number) => 0.52 * (1 - Math.exp(-t * 5.2));
  let previous = -1;
  for (let step = 0; step <= 100; step += 1) {
    const t = step / 100;
    const value = normal.values(t);
    assert.ok(value >= previous - 1e-9, `убывает на ${t}`);
    assert.ok(value <= typical(t) * 1.34 + 1e-9 && value >= typical(t) * 0.68 - 1e-9, `вне разброса на ${t}`);
    previous = value;
  }
  assert.equal(corridorCrowd().length, 5);
});

test("экран телефона: площадки со своими суммами и просмотрами по дням", () => {
  const data = {
    period: "30d", hours: [], datasetRevision: 1, asOf: "2026-09-26T00:00:00Z", institutions: [], curves: [], timing: [], types: [],
    daily: [
      { platform: "vk", day: "2026-09-25", posts: 10, viewsTotal: 1000, reactionsTotal: 5, analyzed: 10, anomalous: 1 },
      { platform: "vk", day: "2026-09-24", posts: 5, viewsTotal: null, reactionsTotal: 1, analyzed: 5, anomalous: 0 },
      { platform: "telegram", day: "2026-09-25", posts: 3, viewsTotal: 300, reactionsTotal: 2, analyzed: 3, anomalous: 0 },
    ],
    stats: [{ institutionId: null, platform: "vk", views24: 120, engagement24: 2.5, analyzed: 20, levels: [15, 2, 2, 1] }],
  } as unknown as Dashboard;
  const summary = phoneSummary(data);
  assert.deepEqual(summary.days, ["2026-09-24", "2026-09-25"]);
  assert.deepEqual(summary.networks.map((network) => network.platform), ["telegram", "vk"]);
  const vk = summary.networks.find((network) => network.platform === "vk")!;
  assert.deepEqual([vk.posts, vk.views, vk.daily, vk.views24, vk.anomalyShare], [15, 1000, [0, 1000], 120, 0.15]);
  assert.equal(summary.networks.find((network) => network.platform === "telegram")!.anomalyShare, null);
});
