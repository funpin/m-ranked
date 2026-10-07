import assert from "node:assert/strict";
import test from "node:test";
import {
  SIGNAL_LEGEND, boundarySnapshotIds, intervalText, miniChart, referenceExplanation, scaleText, signalCount, signalMarkers, summaryLine,
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
    originalLevel: 2, recheckReason: null, recheckMethodVersion: null, recheckEvidence: null,
    analyzedAt: at(70), lagSeconds: 0, normVersion: 1, detectorVersions: {}, reviewStatus: "unreviewed",
    accountFindings: [], methodologyVersion: "anomaly-dynamics-v2", disclaimer: "", ...overrides,
  };
}

test("collapsed line names the level, counts signals and stays calm without them", () => {
  const strong = summaryLine(analysis({ signals: [signal(), signal({ pattern: 6 })] }));
  assert.deepEqual([strong.level, strong.label, strong.count, strong.calm, strong.tone], [2, "выраженная аномалия", "2 признака", false, "amber"]);
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

test("interval boundaries become the nearest saved points and markers keep their patterns", () => {
  assert.deepEqual([...boundarySnapshotIds(analysis(), rows)], ["41", "65"]);
  assert.equal(boundarySnapshotIds(null, rows).size, 0);
  const [marker] = signalMarkers(analysis());
  assert.equal(marker!.pattern, 1);
  assert.equal(marker!.to - marker!.from, 24 * 3600_000);
  assert.equal(new Set(SIGNAL_LEGEND.map((item) => item.pattern)).size, 15);
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

test("a production late-engagement signal renders saved rates without age fields", () => {
  const late = signal({ pattern: 13, metric: "reactions", render: {
    kind: "late_engagement", earlyRate: 0.02, lateRate: 0.12, ratio: 6,
  } } as unknown as Partial<AnomalySignal>);
  const chart = miniChart(late, [], PUBLISHED);
  assert.equal(chart.type, "bars");
  if (chart.type !== "bars") return;
  assert.equal(chart.percent, true);
  assert.deepEqual(chart.bars.map(({ value, highlight }) => [value, highlight]), [[0.02, false], [0.12, true]]);
});

test("endpoint references reuse bars with saved counts and explicit historical scope", () => {
  const s = signal({ pattern: 12, render: { kind: "reference", startAge: 86400, endAge: 259200,
    observed: 900, expected: 310, upper: 520, fitPosts: 266, calibrationPosts: 130,
    referenceStart: "2026-09-06T00:00:00Z", referenceEnd: "2026-09-17T00:00:00Z" } });
  const chart = miniChart(s, [], PUBLISHED);
  assert.equal(chart.type, "bars");
  assert.deepEqual(chart.type === "bars" ? chart.bars.map(bar => bar.value) : [], [900, 310, 520]);
  assert.match(referenceExplanation(s)!, /первым суткам/);
  assert.match(referenceExplanation(s)!, /130 для общей границы/);
  assert.match(referenceExplanation(s)!, /не означает вероятность/);
  assert.equal(referenceExplanation(signal()), null);
});

test("no precise metrics is an abstention, not a calm normality claim", () => {
  const line = summaryLine(analysis({ level: 0, signals: [], quality: {
    coverage: 0, codes: ["no_precise_metrics"], summary: "нет точных данных", unanalyzable: [] } }));
  assert.equal(line.label, "недостаточно точных данных");
  assert.equal(line.level, null);
  assert.equal(line.tone, "neutral");
});

test("bounded reaction evidence stays visible without exact counters and uses endpoint bars", () => {
  const bounded = signal({ pattern: 9, metric: "reactions", render: {
    kind: "bounded_burst", startAge: 6 * 3600, endAge: 7 * 3600,
    beforeRange: [25, 33], afterRange: [1063, 1089], timingUnknown: true,
  } });
  const line = summaryLine(analysis({ signals: [bounded], quality: {
    coverage: 0, codes: ["no_precise_metrics", "bounded_reaction_counts"],
    summary: "Оценка с допуском на округление", unanalyzable: [],
  } }));
  assert.equal(line.level, 2);
  assert.equal(line.label, "выраженная аномалия");
  const chart = miniChart(bounded, [], PUBLISHED);
  assert.equal(chart.type, "bars");
  assert.deepEqual(chart.type === "bars" ? chart.bars.map(item => item.value) : [], [25, 33, 1063, 1089]);
});

test("initial plateau shows the actual first count and highest status even without exact metrics", () => {
  const initial = signal({ pattern: 9, metric: "reactions", render: {
    kind: "bounded_burst", mode: "initial_plateau", startAge: 342, endAge: 11444,
    beforeRange: [105,117], afterRange: [122,136], timingUnknown: true,
  } });
  const report = analysis({ level: 3, levelLabel: "признаки искусственной активности", signals: [initial],
    quality: { coverage: 0, codes: ["no_precise_metrics"], summary: "Округлённые счётчики", unanalyzable: [] } });
  assert.equal(summaryLine(report).level, 3);
  assert.equal(signalMarkers(report)[0].tone, "priority");
  const chart = miniChart(initial, [], PUBLISHED);
  assert.equal(chart.type, "bars");
  if (chart.type === "bars") {
    assert.deepEqual(chart.bars.map(item => item.value), [105,117,122,136]);
    assert.match(chart.bars[0].label, /первый замер/);
    assert.match(chart.bars[2].label, /плато/);
  }
});

test("unconfirmed shape shows reported counts without invented precision bounds", () => {
  const candidate = signal({ pattern: 9, metric: "reactions", render: {
    kind: "bounded_burst", startAge: 552, endAge: 852,
    reportedOnly: true, reportedBefore: 11, reportedAfter: 119,
  } });
  const chart = miniChart(candidate, [], PUBLISHED);
  assert.equal(chart.type, "bars");
  if (chart.type === "bars") {
    assert.deepEqual(chart.bars.map(item => item.value), [11, 119]);
    assert.deepEqual(chart.bars.map(item => item.label), ["сохранено до", "сохранено после"]);
  }
});

test("late engagement compares the same post's early and late reaction shares", () => {
  const chart = miniChart(signal({
    pattern: 13, family: "cross_metric", metric: "reactions", strength: 0.6,
    render: { kind: "late_engagement", startAge: 96 * 3600, endAge: 13 * 86400, earlyRate: 0.013, lateRate: 0.33 },
  }), rows, PUBLISHED);
  assert.equal(chart.type, "bars");
  if (chart.type !== "bars") return;
  assert.equal(chart.percent, true);
  assert.deepEqual(chart.bars.map((bar) => [bar.label, bar.value, bar.highlight]),
    [["первые сутки", 0.013, false], ["после 4 суток", 0.33, true]]);
});
