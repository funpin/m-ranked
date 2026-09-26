import assert from "node:assert/strict";
import test from "node:test";
import {
  formatValue, hourlyReach, institutionRows, median, normalizeDashboardPeriod, normalizeDashboardPlatform,
  percentileRank, platformSummary, sortRows, timingGrid, type Dashboard, type DashboardStat,
} from "../lib/compare-dashboard";

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
