import assert from "node:assert/strict";
import test from "node:test";
import {
  SIGNAL_LEGEND, boundarySnapshotIds, intervalText, miniChart, scaleText, signalCount, signalMarkers, summaryLine,
} from "../lib/anomaly";
import type { AnomalySignal, HistorySnapshot, PublicationAnomalyAnalysis } from "../lib/types";

const PUBLISHED = "2026-07-01T00:00:00Z";
const at = (hours: number) => new Date(Date.parse(PUBLISHED) + hours * 3600_000).toISOString();
const counter = (value: number | null): HistorySnapshot["views"] => ({ value, observedAt: null, quality: "exact" });
const rows: HistorySnapshot[] = Array.from({ length: 72 }, (_, index) => ({
  snapshotId: String(index + 1), observedAt: at(index), ageHours: index,
  views: counter(index < 40 ? 100 + index : 140 + (index - 40) * 50), reactions: counter(index),
  comments: counter(0), shares: counter(null),
  deltaViews: null, deltaReactions: null, deltaComments: null, deltaShares: null,
  reactionsBreakdown: null, deltaReactionsBreakdown: null, reactionsBreakdownEntries: null, deltaReactionsBreakdownEntries: null,
  synthetic: false, intervalUncertain: false, quality: "exact", rawEvidence: null, collectorInterval: null,
}) as unknown as HistorySnapshot);

function signal(overrides: Partial<AnomalySignal> = {}): AnomalySignal {
  return {
    pattern: 1, symbol: "⟋", title: "Линейная подача", family: "velocity", metric: "views", strength: 0.9,
    startAt: at(40), endAt: at(64), scaleSeconds: 3600, formula: "Δпросмотры ≈ 50·t",
    render: { kind: "linear", startAge: 40 * 3600, endAge: 64 * 3600, slope: 50, intercept: 140 },
    alternatives: [], normConfidence: null, ...overrides,
  };
}

function analysis(overrides: Partial<PublicationAnomalyAnalysis> = {}): PublicationAnomalyAnalysis {
  return {
    publicationId: "10000000-0000-4000-8000-000000000001", datasetRevision: 1, status: "analyzed", level: 2,
    levelLabel: "выраженная аномалия", levelSymbol: "◑", signals: [signal()], quality: null,
    analyzedAt: at(70), lagSeconds: 0, normVersion: 1, detectorVersions: {}, reviewStatus: "unreviewed",
    methodologyVersion: "anomaly-dynamics-v2", disclaimer: "", ...overrides,
  };
}

test("collapsed line names the level, counts signals and stays calm without them", () => {
  const strong = summaryLine(analysis({ signals: [signal(), signal({ pattern: 6 })] }));
  assert.deepEqual([strong.symbol, strong.label, strong.count, strong.calm, strong.tone], ["◑", "выраженная аномалия", "2 признака", false, "amber"]);
  assert.equal(summaryLine(analysis({ level: 3 })).tone, "red");
  const none = summaryLine(analysis({ level: 0, signals: [], levelLabel: "нет признаков", levelSymbol: "○" }));
  assert.equal(none.calm, true);
  assert.equal(none.count, null);
  assert.equal(summaryLine(analysis({ level: null, status: "pending", signals: [] })).tone, "neutral");
});

test("russian plurals and scales read naturally", () => {
  assert.deepEqual([1, 2, 5, 11, 21, 104].map(signalCount), ["1 признак", "2 признака", "5 признаков", "11 признаков", "21 признак", "104 признака"]);
  assert.equal(scaleText(900), "15 мин");
  assert.equal(scaleText(21600), "6 ч");
  assert.equal(intervalText(signal(), PUBLISHED), "1 д 16 ч 0 мин — 2 д 16 ч 0 мин после публикации");
});

test("interval boundaries become the nearest saved points and markers keep their symbols", () => {
  assert.deepEqual([...boundarySnapshotIds(analysis(), rows)], ["41", "65"]);
  assert.equal(boundarySnapshotIds(null, rows).size, 0);
  const [marker] = signalMarkers(analysis());
  assert.equal(marker!.symbol, "⟋");
  assert.equal(marker!.to - marker!.from, 24 * 3600_000);
  assert.equal(new Set(SIGNAL_LEGEND.map((item) => item.symbol)).size, 9);
});

test("linear signal draws its fitted line only inside the interval", () => {
  const chart = miniChart(signal(), rows, PUBLISHED);
  assert.equal(chart.type, "lines");
  if (chart.type !== "lines") return;
  const inside = chart.points.find((point) => point.t === Date.parse(at(50)))!;
  const outside = chart.points.find((point) => point.t === Date.parse(at(30)))!;
  assert.equal(inside.fit, 140 + 50 * 10);
  assert.equal(outside.fit, null);
  assert.ok(chart.points.every((point) => point.t! >= Date.parse(at(28)) && point.t! <= Date.parse(at(71))));
});

test("late spike compares the actual curve with a model band", () => {
  const chart = miniChart(signal({ pattern: 2, render: { kind: "expected", startAge: 40 * 3600, endAge: 48 * 3600, decay: [10, 1.2, 1], expected: 20 } }), rows, PUBLISHED);
  assert.equal(chart.type, "lines");
  if (chart.type !== "lines") return;
  const point = chart.points.find((item) => item.t === Date.parse(at(46)))!;
  assert.ok(point.expected! > 140 && point.low! < point.expected! && point.high! > point.expected!);
  assert.ok(point.actual! > point.high!, "скачок выходит за полосу модели");
});

test("cross-metric signals overlay reactions and views, ERV and synchrony are bars", () => {
  const lead = miniChart(signal({ pattern: 6, metric: "reactions", render: { kind: "lead", startAge: 40 * 3600, endAge: 42 * 3600 } }), rows, PUBLISHED);
  assert.deepEqual(lead.type === "lines" ? lead.series.map((item) => item.axis) : [], ["left", "right"]);
  const erv = miniChart(signal({ pattern: 10, render: { kind: "erv", startAge: 0, endAge: 86400, erv: 0.13, median: 0.037 } }), rows, PUBLISHED);
  assert.deepEqual(erv.type === "bars" ? erv.bars.map((bar) => bar.value) : [], [0.13, 0.037]);
  const sync = miniChart(signal({ pattern: 8, render: { kind: "synchrony", startAge: 0, endAge: 3600, posts: 5, quiet: 2 } }), rows, PUBLISHED);
  assert.deepEqual(sync.type === "bars" ? sync.bars.map((bar) => bar.value) : [], [5, 2]);
});
