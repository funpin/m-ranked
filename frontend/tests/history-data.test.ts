import assert from "node:assert/strict";
import test from "node:test";
import { sampleHistory, historyReactionEntries } from "../lib/history-data";
const rows=Array.from({length:2000},(_,index) => ({snapshotId:String(index),reactionsBreakdown:{"👍":index}}));
test("history sampling keeps endpoints, selected observation and 144 point budget",() => {
  const sampled=sampleHistory(rows,10,1990,"753");
  assert.ok(sampled.length <= 144);assert.equal(sampled[0]?.snapshotId,"10");assert.equal(sampled.at(-1)?.snapshotId,"1990");assert.ok(sampled.some((row) => row.snapshotId === "753"));
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
