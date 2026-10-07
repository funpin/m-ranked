import assert from "node:assert/strict";
import test from "node:test";
import { sampleHistory, historyReactionEntries } from "../lib/history-data";
const rows=Array.from({length:2000},(_,index) => ({snapshotId:String(index),reactionsBreakdown:{"👍":index}}));
test("history sampling keeps endpoints, selected observation and 144 point budget",() => {
  const sampled=sampleHistory(rows,10,1990,"753");
  assert.ok(sampled.length <= 144);assert.equal(sampled[0]?.snapshotId,"10");assert.equal(sampled.at(-1)?.snapshotId,"1990");assert.ok(sampled.some((row) => row.snapshotId === "753"));
  const evidence=sampleHistory(rows,10,1990,undefined,["611","1201"]);
  assert.ok(evidence.some((row)=>row.snapshotId==="611"));assert.ok(evidence.some((row)=>row.snapshotId==="1201"));
  assert.equal(sampleHistory(rows,10,20).length,11);
});
test("history uses retained signed deltas and reaction order without normalizing keys",() => {
  const entries=[{reaction:"custom:123",count:8},{reaction:"❤",count:4}];
  const delta=[{reaction:"❤",count:-1},{reaction:"👍",count:-1}];
  const row={reactionsBreakdown:{"❤":4,"custom:123":8},reactionsBreakdownEntries:entries,deltaReactionsBreakdown:{"👍":-1,"❤":-1},deltaReactionsBreakdownEntries:delta};
  assert.equal(historyReactionEntries(row),entries);
  assert.equal(historyReactionEntries(row,true),delta);
  assert.equal(historyReactionEntries({...row,deltaReactionsBreakdown:null,deltaReactionsBreakdownEntries:null},true),null);
});

test("a long history is previewed: chart sample plus full table tail, no lineage", async () => {
  const { previewHistory } = await import("../lib/history-data");
  const row = (index: number) => ({ snapshotId: String(index + 1), observedAt: new Date(Date.UTC(2026, 6, 1) + index * 3_600_000).toISOString(),
    rawEvidence: { sourceFingerprint: "f".repeat(64) }, collectorInterval: index ? { from: "a", to: "b", successfulPolls: 1, failedPolls: 0 } : null }) as never;
  const short = previewHistory(Array.from({ length: 200 }, (_, index) => row(index)), 100);
  assert.equal(short.sampledIds, null);
  assert.equal(short.rows.length, 200);
  const items = Array.from({ length: 1205 }, (_, index) => row(index));
  const preview = previewHistory(items, 100);
  assert.equal(preview.totalPoints, 1205);
  assert.ok(preview.sampledIds && preview.sampledIds.length <= 144);
  assert.ok(preview.rows.length < 250);
  // Хвост таблицы — последние 101 строка полностью, с интервалом сборщика.
  const tail = preview.rows.slice(-101) as { snapshotId: string; collectorInterval: unknown; rawEvidence: object }[];
  assert.deepEqual(tail.map((item) => item.snapshotId), items.slice(-101).map((item) => (item as { snapshotId: string }).snapshotId));
  assert.ok(tail.every((item) => item.collectorInterval !== null));
  const chartOnly = (preview.rows as { snapshotId: string; collectorInterval: unknown }[]).filter((item) => Number(item.snapshotId) < 1105);
  assert.ok(chartOnly.length > 100 && chartOnly.every((item) => item.collectorInterval === null));
  assert.ok((preview.rows as { rawEvidence: object }[]).every((item) => Object.keys(item.rawEvidence).length === 0));
  assert.equal((preview.rows[0] as { snapshotId: string }).snapshotId, "1");
});

test("an unchanged read before growth becomes a chart point with the previous values", async () => {
  const { withUnchangedReads } = await import("../lib/history-data");
  const counter = (value: number | null) => ({ value, observedAt: null, quality: "exact" });
  const base = { ageHours: 0, comments: counter(0), shares: counter(null), deltaComments: 0, deltaShares: null,
    reactionsBreakdown: null, deltaReactionsBreakdown: null, reactionsBreakdownEntries: null, deltaReactionsBreakdownEntries: null,
    synthetic: false, intervalUncertain: false, quality: "exact", rawEvidence: {} };
  // RuTube e6953fb9: 1 просмотр в 14:16, через 18 ч — 1 749; последний цикл без изменений — 07:15.
  const rows = [
    { ...base, snapshotId: "1", observedAt: "2026-09-28T14:16:15Z", views: counter(1), reactions: counter(0),
      deltaViews: null, deltaReactions: null, collectorInterval: null },
    { ...base, snapshotId: "2", observedAt: "2026-09-29T08:16:27Z", ageHours: 18.25, views: counter(1749), reactions: counter(97),
      deltaViews: 1748, deltaReactions: 97, collectorInterval: { from: "2026-09-28T14:16:15Z", to: "2026-09-29T08:16:27Z",
        successfulPolls: 18, failedPolls: 0, unchangedAt: "2026-09-29T07:15:02Z" } },
  ] as never[];
  const plotted = withUnchangedReads(rows);
  assert.deepEqual(plotted.map((row) => [row.observedAt, row.views.value, row.reactions.value, row.unchangedFor ?? null]), [
    ["2026-09-28T14:16:15Z", 1, 0, null],
    ["2026-09-29T07:15:02Z", 1, 0, "2"],
    ["2026-09-29T08:16:27Z", 1749, 97, null],
  ]);
  // Чтение не позже прошлой точки (например, в выборке) ничего не добавляет.
  assert.equal(withUnchangedReads([rows[1]!]).length, 1);
});
