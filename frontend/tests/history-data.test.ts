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
