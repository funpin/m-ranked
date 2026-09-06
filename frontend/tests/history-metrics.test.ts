import assert from "node:assert/strict";
import test from "node:test";
import { availableHistoryMetrics, historyMetrics, historyMetricValue, historyMetricTooltip, historyRatioTooltip } from "../lib/history-metrics";
import { sampleHistory } from "../lib/history-data";
import type { HistorySnapshot } from "../lib/types";

const counter = (value:number|null) => ({value,observedAt:null,quality:null});
const row = (index:number):HistorySnapshot => ({snapshotId:String(index),observedAt:"2026-09-06T00:00:00Z",ageHours:index,
  reactions:counter(index),views:counter(index*10),comments:counter(null),shares:counter(null),
  deltaReactions:index === 500 ? -3 : index === 700 ? null : 1,deltaViews:10,deltaComments:null,deltaShares:null,
  reactionsBreakdown:{},reactionsBreakdownEntries:[],deltaReactionsBreakdown:null,deltaReactionsBreakdownEntries:null,
  synthetic:false,intervalUncertain:false,quality:"exact",rawEvidence:{}});

test("sampling and zoom preserve stored interval deltas, negative corrections and missing values", () => {
  const rows=Array.from({length:2000},(_,index)=>row(index));
  const reactions=historyMetrics[0];
  const sampled=sampleHistory(rows,0,1999,"500");
  assert.equal(sampled.length,144);
  assert.equal(historyMetricValue(sampled[1]!,reactions,true),1);
  assert.ok(sampled[1]!.reactions.value! - sampled[0]!.reactions.value! > 1);
  assert.equal(historyMetricValue(sampled.find(row=>row.snapshotId==="500")!,reactions,true),-3);
  assert.equal(historyMetricValue(sampleHistory(rows,700,702)[0]!,reactions,true),null);
  assert.equal(historyMetricTooltip(rows[500]!,reactions,"telegram",true),"Прирост реакций: -3");
  assert.equal(historyMetricTooltip(rows[701]!,reactions,"max",true),"Прирост реакций: +1");
});

test("one metric policy hides unavailable counters but retains observed zero", () => {
  assert.deepEqual(availableHistoryMetrics([row(0)]).map(metric=>metric.key),["reactions","views"]);
  assert.deepEqual(availableHistoryMetrics([{...row(0),comments:counter(0)}]).map(metric=>metric.key),["reactions","views","comments"]);
});

test("same-observation reaction ratios work for every platform and never divide missing or zero views", () => {
  const point={...row(0),reactions:counter(81),views:counter(105)};
  for(const platform of ["telegram","max"]) assert.equal(historyRatioTooltip(point,platform),"Реакции / просмотры: 77.14%");
  for(const platform of ["vk","rutube"]) assert.equal(historyRatioTooltip(point,platform),"Лайки / просмотры: 77.14%");
  assert.equal(historyRatioTooltip({...point,views:counter(0)},"telegram"),"");
  assert.equal(historyRatioTooltip({...point,reactions:counter(null)},"vk"),"");
  assert.equal(historyRatioTooltip({...point,reactions:counter(0)},"max"),"Реакции / просмотры: 0.00%");
});
