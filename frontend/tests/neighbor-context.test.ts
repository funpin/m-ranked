import assert from "node:assert/strict";
import { test } from "node:test";
import { assessNeighborContext, bracketViews, evaluateNeighborContext } from "../lib/neighbor-context";
import { alignedEventGrowth } from "../components/neighbor-context-timeline";
import { signalMarkers } from "../lib/anomaly";
import type { HistorySnapshot, PublicationAnomalyAnalysis, PublicationHistory, PublicationListItem } from "../lib/types";

const start = "2026-09-14T12:00:00Z", end = "2026-09-14T13:00:00Z";
function point(observedAt: string, views: number, quality = "rounded"): HistorySnapshot {
  return { observedAt, views: { value: views, quality }, synthetic: false, intervalUncertain: false } as HistorySnapshot;
}
function history(id: string, rows: HistorySnapshot[]): PublicationHistory {
  return { publication: { publicationId: id }, items: rows } as PublicationHistory;
}
function post(publicationId: string, displayExternalId: string, publishedAt: string): PublicationListItem {
  return { publicationId, displayExternalId, publishedAt } as PublicationListItem;
}

test("a missing or too distant post read never becomes a zero growth observation", () => {
  assert.equal(bracketViews(history("old", [point("2026-09-14T11:50:00Z", 100)]), start, end), null);
  assert.equal(bracketViews(history("old", [point("2026-09-14T07:00:00Z", 100), point("2026-09-14T13:05:00Z", 100)]), start, end), null);
  const bracket = bracketViews(history("old", [point("2026-09-14T11:50:00Z", 100), point("2026-09-14T13:05:00Z", 110)]), start, end);
  assert.equal(bracket?.displayedDelta, 10);
  assert.equal(bracket?.rounded, true);
});

test("a late signal records both nearby publication and co-moving old posts without assigning a calibrated probability", () => {
  const analysis = { signals: [{ pattern: 2, metric: "views", startAt: start, endAt: end,
    strength: 0.9, formula: "факт выше ожидания" }] } as PublicationAnomalyAnalysis;
  const publications = [
    post("p1", "11340", "2026-09-11T08:00:00Z"),
    post("p2", "11341", "2026-09-11T09:00:00Z"),
    post("target", "11342", "2026-09-12T08:30:00Z"),
    post("new", "11343", "2026-09-14T12:20:00Z"),
  ];
  const points = (before: number, after: number) => [point("2026-09-14T11:50:00Z", before), point("2026-09-14T13:05:00Z", after)];
  const windows = evaluateNeighborContext({ analysis, targetHistory: history("target", [
    point("2026-09-14T11:50:00Z", 2800), point("2026-09-14T12:30:00Z", 2850), point("2026-09-14T13:05:00Z", 2900),
  ]), publications,
    peerHistories: new Map([["p1", history("p1", points(2000, 2050))], ["p2", history("p2", points(2500, 2570))],
      ["new", history("new", [point("2026-09-14T12:25:00Z", 20), point("2026-09-14T12:55:00Z", 80)])]]) });
  assert.equal(windows.length, 1);
  assert.equal(windows[0]?.context, "neighbor_and_shared");
  assert.equal(windows[0]?.positivePeerCount, 2);
  assert.deepEqual(windows[0]?.events.map((event) => event.displayId), ["11343"]);
  assert.deepEqual(windows[0]?.targetTrace.map((point) => point.views), [2800, 2850, 2900]);
  assert.deepEqual(windows[0]?.eventTraces[0]?.points.map((point) => point.views), [20, 80]);
  assert.deepEqual(windows[0]?.eventTraces[0]?.points.map((point) => point.observedAt),
    ["2026-09-14T12:25:00Z", "2026-09-14T12:55:00Z"]);
  assert.equal(typeof windows[0]?.conditionalLogResidual, "number");
  assert.deepEqual(assessNeighborContext(analysis, windows, true), {
    status: "insufficient_data", contextualized: 1, totalLateSpikes: 1,
    residualExcess: 0, compatible: 0, unevaluated: 1,
  });
  assert.equal(assessNeighborContext(analysis, windows, false).status, "insufficient_data");
});

test("context does not override an independent signal or missing comparison data", () => {
  const late = { pattern: 2, metric: "views", startAt: start, endAt: end,
    strength: 0.9, formula: "late" };
  const independent = { pattern: 7, metric: "reactions", startAt: start, endAt: end,
    strength: 0.8, formula: "independent" };
  const publications = [post("p1", "1", "2026-09-11T08:00:00Z"),
    post("p2", "2", "2026-09-11T09:00:00Z"),
    post("target", "3", "2026-09-12T08:30:00Z")];
  const rows = [point("2026-09-14T11:50:00Z", 100), point("2026-09-14T13:05:00Z", 110)];
  const input = { targetHistory: history("target", rows), publications,
    peerHistories: new Map([["p1", history("p1", rows)], ["p2", history("p2", rows)]]) };
  const mixed = { signals: [late, independent] } as PublicationAnomalyAnalysis;
  const windows = evaluateNeighborContext({ ...input, analysis: mixed });
  assert.equal(assessNeighborContext(mixed, windows, true).status, "other_evidence");
  const missing = evaluateNeighborContext({ ...input, analysis: { signals: [late] } as PublicationAnomalyAnalysis,
    peerHistories: new Map() });
  assert.equal(assessNeighborContext({ signals: [late] } as PublicationAnomalyAnalysis, missing, true).status, "insufficient_data");
});

test("a post 33 seconds before a rounded signal and farther down the feed stays visible", () => {
  const from = "2026-09-17T06:30:00Z", to = "2026-09-17T13:30:00Z";
  const published = "2026-09-17T06:29:27Z";
  const publications = [post("p1", "11340", "2026-09-11T08:00:00Z"),
    post("p2", "11341", "2026-09-11T09:00:00Z"),
    post("target", "11342", "2026-09-12T08:30:00Z"),
    ...Array.from({ length: 10 }, (_, i) => post(`middle${i}`, String(11343 + i), "2026-09-16T08:00:00Z")),
    post("new", "11354", published)];
  const analysis = { signals: [{ pattern: 2, metric: "views", startAt: from, endAt: to,
    scaleSeconds: 900, strength: 0.9, formula: "late" }] } as PublicationAnomalyAnalysis;
  const targetHistory = history("target", [point("2026-09-17T06:00:00Z", 2800),
    point("2026-09-17T07:00:00Z", 2820), point("2026-09-17T13:35:00Z", 3100)]);
  const windows = evaluateNeighborContext({ analysis, targetHistory, publications,
    peerHistories: new Map([["new", history("new", [point("2026-09-17T06:40:00Z", 20), point("2026-09-17T08:00:00Z", 200)])]]) });
  assert.equal(windows[0]?.events[0]?.displayId, "11354");
  assert.ok((windows[0]?.events[0]?.observedFeedDistance ?? 0) > 4);
  assert.equal(windows[0]?.eventTraces[0]?.publicationId, "new");
  const aligned = alignedEventGrowth(windows[0]!, windows[0]!.events[0]!);
  assert.ok(aligned);
  assert.ok(aligned.anchor.growth > 0 && aligned.anchor.growth < 20);
  assert.equal(aligned.observations[0]?.growth, aligned.anchor.growth + 20);
});

test("M2 contrasts each post with its own observed quiet window, then subtracts peers", () => {
  const analysis = { signals: [{ pattern: 2, metric: "views", startAt: start, endAt: end,
    scaleSeconds: 900, strength: 0.8, formula: "late" }] } as PublicationAnomalyAnalysis;
  const publications = [post("p1", "1", "2026-09-11T08:00:00Z"),
    post("p2", "2", "2026-09-11T09:00:00Z"),
    post("target", "3", "2026-09-12T08:30:00Z"),
    post("new", "4", "2026-09-14T12:20:00Z")];
  const rows = (base: number, quiet: number, event: number) => [
    point("2026-09-13T14:00:00Z", base),
    point("2026-09-13T15:00:00Z", base + quiet),
    point("2026-09-14T12:00:00Z", base + quiet),
    point("2026-09-14T13:00:00Z", base + quiet + event),
  ];
  const targetHistory = history("target", rows(100, 10, 50));
  const peerHistories = new Map([
    ["p1", history("p1", rows(100, 5, 15))],
    ["p2", history("p2", rows(200, 5, 15))],
  ]);
  const [window] = evaluateNeighborContext({ analysis, targetHistory, publications, peerHistories });
  assert.equal(window?.matchedContrast?.targetExtraPerHour, 40);
  assert.equal(window?.matchedContrast?.peerExtraMedianPerHour, 10);
  assert.equal(window?.matchedContrast?.residualPerHour, 30);
  assert.equal(window?.matchedContrast?.matchedPeerCount, 2);
  assert.deepEqual(assessNeighborContext(analysis, [window!], true), {
    status: "residual_excess", contextualized: 1, totalLateSpikes: 1,
    residualExcess: 1, compatible: 0, unevaluated: 0,
  });
  assert.equal(signalMarkers(analysis, [window!])[0]?.tone, "review");
  assert.equal(signalMarkers({ ...analysis, level: 3 }, [window!])[0]?.tone, "priority");
  const compatibleWindow = { ...window!, matchedContrast: {
    ...window!.matchedContrast!, residualPerHour: -1,
  } };
  assert.equal(assessNeighborContext(analysis, [compatibleWindow], true).status, "context_compatible");
  assert.equal(signalMarkers(analysis, [compatibleWindow])[0]?.tone, "context_views");
  const noQuiet = evaluateNeighborContext({ analysis, targetHistory: history("target", rows(100, 10, 50).slice(2)),
    publications, peerHistories });
  assert.equal(noQuiet[0]?.matchedContrast, null);
  const noEvent = evaluateNeighborContext({ analysis, targetHistory, publications: publications.slice(0, 3), peerHistories });
  assert.equal(noEvent[0]?.matchedContrast, null);
});
