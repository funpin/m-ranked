import assert from "node:assert/strict";
import { test } from "node:test";
import { assessNeighborContext, bracketViews, evaluateNeighborContext } from "../lib/neighbor-context";
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
  const windows = evaluateNeighborContext({ analysis, targetHistory: history("target", points(2800, 2900)), publications,
    peerHistories: new Map([["p1", history("p1", points(2000, 2050))], ["p2", history("p2", points(2500, 2570))]]) });
  assert.equal(windows.length, 1);
  assert.equal(windows[0]?.context, "neighbor_and_shared");
  assert.equal(windows[0]?.positivePeerCount, 2);
  assert.deepEqual(windows[0]?.events.map((event) => event.displayId), ["11343"]);
  assert.equal(typeof windows[0]?.conditionalLogResidual, "number");
  assert.deepEqual(assessNeighborContext(analysis, windows, true), {
    status: "requires_review", contextualized: 1, totalLateSpikes: 1,
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
