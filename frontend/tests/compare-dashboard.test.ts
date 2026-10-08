import assert from "node:assert/strict";
import test from "node:test";
import {
  HIGHLIGHT_COLORS, MAX_HIGHLIGHTS, dailyRows, institutionLevels, levelSharesByPlatform, resolveScope, formatValue, highlightMap, hourlyReach, incompleteDay, institutionLabels,
  institutionOptions, institutionRows, median, normalizeDashboardPeriod, normalizeDashboardPlatform, percentileRank,
  platformSummary, sortRows, timingGrid, toggleHighlight, typeName, typeRows, type Dashboard, type DashboardStat,
} from "../lib/compare-dashboard";
import { hourlyOverlay, typeComparison } from "../lib/compare-timing";

const A = "00000009-0000-4000-8000-000000000001";
const B = "00000009-0000-4000-8000-000000000002";

function stat(institutionId: string | null, platform: string, patch: Partial<DashboardStat> = {}): DashboardStat {
  return { institutionId, platform: platform as DashboardStat["platform"], posts: 30, viewsTotal: 1000, reactionsTotal: 50,
    commentsTotal: 3, sharesTotal: null, sample24: 28, views24: 400, reactions24: 20, comments24: 1, shares24: null,
    engagement24: 5, analyzed: 20, levels: [16, 2, 1, 1], ...patch };
}

const data: Dashboard = {
  period: "30d", hours: [1, 24], datasetRevision: 1, asOf: "2026-09-24T00:00:00Z",
  institutions: [
    { institutionId: A, legacyId: 1, name: "Альфа Университет", shortName: "Альфа", platforms: ["telegram", "vk"],
      subscribers: { telegram: 100, vk: 200, max: 0, rutube: 0 } },
    { institutionId: B, legacyId: 2, name: "Бета Институт", shortName: null, platforms: ["vk"],
      subscribers: { telegram: 0, vk: 50, max: 0, rutube: 0 } },
  ],
  stats: [
    stat(A, "telegram", { views24: 900 }), stat(A, "vk", { views24: null, posts: 60 }), stat(A, "all"),
    stat(B, "vk", { views24: 300, analyzed: 0, levels: [0, 0, 0, 0] }), stat(B, "all"),
    stat(null, "vk", { posts: 90, levels: [10, 5, 3, 2] }), stat(null, "all"),
  ],
  curves: [], daily: [],
  timing: [
    { platform: "vk", weekday: 0, hour: 9, posts: 4, views24: 100 },
    { platform: "vk", weekday: null, hour: 9, posts: 11, views24: 150 },
  ],
  types: [],
};

test("rows follow the chosen platform and skip institutions without an account there", () => {
  assert.deepEqual(institutionRows(data, "telegram").map((row) => row.name), ["Альфа"]);
  const vk = institutionRows(data, "vk");
  assert.deepEqual(vk.map((row) => row.name), ["Альфа", "Бета Институт"]);
  assert.equal(vk[0]!.postsPerDay, 2);
  assert.equal(vk[0]!.subscribers, 200);
  assert.equal(institutionRows(data, "all")[0]!.subscribers, 300);
});

test("subscribers distinguish missing, partial and measured zero counts", () => {
  const partial: Dashboard = { ...data, institutions: [
    { ...data.institutions[0]!, subscribers: { telegram: null, vk: 0, max: null, rutube: null } },
    { ...data.institutions[1]!, subscribers: { telegram: 900, vk: null, max: null, rutube: null } },
  ] };
  const rows = institutionRows(partial, "all");
  assert.equal(rows[0]!.subscribers, 0);
  assert.equal(rows[0]!.subscriberNetworks, 1);
  assert.equal(rows[0]!.connectedNetworks, 2);
  assert.equal(rows[1]!.subscribers, null); // Disconnected TG must not enter VK's sum.
  assert.equal(institutionRows(partial, "telegram")[0]!.subscribers, null);
  for (const descending of [true, false]) {
    assert.deepEqual(sortRows(rows, "subscribers", descending).map(row => row.id), [A, B]);
  }
});

test("student facts retain their source and remain optional for older responses", () => {
  const students = { value: 12345, referenceYear: 2026, approximate: false,
    sourceUrl: "https://example.test/students", sourceLabel: "Официальный отчёт",
    scope: "Все формы обучения", verifiedAt: "2026-10-03" };
  const rows = institutionRows({ ...data, institutions: [
    { ...data.institutions[0]!, students }, data.institutions[1]!,
  ] }, "all");
  assert.equal(rows[0]!.students, 12345);
  assert.deepEqual(rows[0]!.studentFact, students);
  assert.equal(rows[1]!.students, null);
});

test("anomaly share counts levels 2–3 among analysed posts and is empty without analysis", () => {
  const [alpha, beta] = institutionRows(data, "vk");
  assert.equal(alpha!.anomalyShare, 10);
  assert.equal(beta!.anomalyShare, null);
  assert.equal(platformSummary(data, "vk", institutionRows(data, "vk")).anomalyShare, 25);
});

test("sorting puts missing values last whatever the direction", () => {
  const rows = institutionRows(data, "vk");
  assert.deepEqual(sortRows(rows, "views24").map((row) => row.name), ["Бета Институт", "Альфа"]);
  assert.deepEqual(sortRows(rows, "views24", false).map((row) => row.name), ["Бета Институт", "Альфа"]);
});

test("percentile rank puts the best at 100 and inverts where lower is better", () => {
  const rows = institutionRows(data, "telegram").concat(institutionRows(data, "vk"));
  const best = rows.find((row) => row.views24 === 900)!;
  assert.equal(percentileRank(rows, best, "views24"), 100);
  assert.equal(median([3, 1, 2]), 2);
  assert.equal(median([4, 1, 2, 3]), 2.5);
  assert.equal(median([]), null);
});

test("hourly reach reads the all-weekday medians, the grid the per-day cells", () => {
  const reach = hourlyReach(data, "vk");
  assert.equal(reach[9]!.views24, 150);
  assert.equal(reach[9]!.posts, 11);
  assert.equal(reach[10]!.views24, null);
  assert.equal(timingGrid(data, "vk")[0]![9]!.posts, 4);
});

test("query values normalise to supported platforms and periods", () => {
  assert.equal(normalizeDashboardPlatform("vk"), "vk");
  assert.equal(normalizeDashboardPlatform("bogus"), "all");
  assert.equal(normalizeDashboardPeriod("7d"), "7d");
  assert.equal(normalizeDashboardPeriod("24"), "30d");
  assert.equal(formatValue(12.345, "engagement24"), "12,3%");
});

test("search options list every university and say why one is missing from the charts", () => {
  const none: Dashboard = { ...data, institutions: [{ ...data.institutions[1]!, platforms: [] }] };
  assert.equal(institutionOptions(none, "all")[0]!.note, "нет аккаунтов в соцсетях");
  const rutube = institutionOptions(data, "rutube");
  assert.deepEqual(rutube.map((option) => option.note), ["нет аккаунта на Rutube", "нет аккаунта на Rutube"]);
  const vk = institutionOptions({ ...data, stats: data.stats.filter((item) => item.institutionId !== B) }, "vk");
  assert.deepEqual(vk.map((option) => [option.name, option.note]), [["Альфа", null], ["Бета Институт", "нет публикаций за период"]]);
  assert.equal(institutionOptions(data, "telegram")[1]!.note, "нет аккаунта в Telegram");
  // Имя метки не зависит от вкладки: Бета есть только во ВКонтакте.
  assert.equal(institutionLabels(data).get(B)?.name, "Бета Институт");
});

test("a highlighted university keeps its colour when another one is removed", () => {
  const ids = Array.from({ length: MAX_HIGHLIGHTS }, (_, index) => `id-${index}`);
  let map = highlightMap(ids.slice(0, 3));
  map = toggleHighlight(map, "id-0");
  assert.equal(map.get("id-1"), HIGHLIGHT_COLORS[1]);
  map = toggleHighlight(map, "id-9");
  assert.equal(map.get("id-9"), HIGHLIGHT_COLORS[0]);
  const full = highlightMap(ids);
  assert.equal(toggleHighlight(full, "extra"), full);
});

test("the unfinished last day moves into dashed keys and keeps the previous point to join them", () => {
  const daily: Dashboard["daily"] = [
    { platform: "vk", day: "2026-09-22", posts: 10, viewsTotal: 100, reactionsTotal: 1, analyzed: 10, anomalous: 1 },
    { platform: "vk", day: "2026-09-23", posts: 12, viewsTotal: 120, reactionsTotal: 1, analyzed: 10, anomalous: 2 },
    { platform: "vk", day: "2026-09-24", posts: 2, viewsTotal: 5, reactionsTotal: 0, analyzed: 0, anomalous: 0 },
  ];
  // 2026-09-24T00:00Z — уже 03:00 24 сентября по Москве.
  const partial = { ...data, daily };
  assert.equal(incompleteDay(partial), "2026-09-24");
  const rows = dailyRows(partial);
  assert.equal(rows[2]!.posts_vk, null);
  assert.equal(rows[2]!.posts_vk_partial, 2);
  assert.equal(rows[1]!.posts_vk, 12);
  assert.equal(rows[1]!.posts_vk_partial, 12);
  assert.equal(rows[0]!.posts_vk_partial, undefined);
  assert.equal(incompleteDay({ ...data, daily: daily.slice(0, 2) }), null);
});

test("formats keep one order with other last and compare a university by share", () => {
  const base = { timing: [], types: [
    { platform: "all" as const, type: "other" as const, posts: 50, views24: 10, engagement24: 1 },
    { platform: "all" as const, type: "photo" as const, posts: 30, views24: 20, engagement24: 1 },
    { platform: "all" as const, type: "video" as const, posts: 20, views24: 30, engagement24: 1 },
  ] };
  assert.deepEqual(typeRows(base, "all").map((row) => [row.type, row.share]), [["Фото", 30], ["Видео", 20], ["Прочее", 50]]);
  assert.equal(typeName("poll"), "Прочее");
  const own = { timing: [], types: [{ platform: "all" as const, type: "video" as const, posts: 4, views24: 90, engagement24: 2 }] };
  const rows = typeComparison(base, "all", [{ id: A, name: "Альфа", color: "red", source: own }]);
  assert.deepEqual(rows.map((row) => [row.type, row[`share_${A}`], row[`views_${A}`]]), [["Фото", 0, null], ["Видео", 100, 90], ["Прочее", 0, null]]);
});

test("a university's hourly line skips hours with too few posts", () => {
  const source = { types: [], timing: [
    { platform: "vk" as const, weekday: null, hour: 9, posts: 2, views24: 900 },
    { platform: "vk" as const, weekday: null, hour: 10, posts: 3, views24: 300 },
  ] };
  const overlay = hourlyOverlay(source, "vk");
  assert.equal(overlay[9], null);
  assert.equal(overlay[10], 300);
});

test("a scoped card follows the latest highlight unless told otherwise", () => {
  assert.equal(resolveScope("auto", []), "all");
  assert.equal(resolveScope("auto", [A, B]), B);
  assert.equal(resolveScope("all", [A, B]), "all");
  assert.equal(resolveScope(A, [A, B]), A);
  // Снятый вуз возвращает карточку к последнему выделенному.
  assert.equal(resolveScope(A, [B]), B);
});

test("anomaly levels narrow to one university and its analysed platforms", () => {
  assert.deepEqual(institutionLevels(data, A, "all"), { analyzed: 20, levels: [16, 2, 1, 1] });
  assert.deepEqual(institutionLevels(data, B, "telegram"), { analyzed: 0, levels: [0, 0, 0, 0] });
  // У Беты на VK ноль проанализированных — площадка не показывается.
  assert.deepEqual(levelSharesByPlatform(data, B), []);
  assert.deepEqual(levelSharesByPlatform(data, A).map((row) => row.platform), ["Telegram", "ВКонтакте"]);
  assert.equal(levelSharesByPlatform(data).length, 4);
});
