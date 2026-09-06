import test from "node:test";
import assert from "node:assert/strict";
import {numericTicks} from "@mranked/legacy-chart";

test("linear scales preserve the observed legacy comparison and correction ranges",()=>{
  assert.deepEqual(numericTicks(0,277,11,0),{min:0,max:300,ticks:[0,50,100,150,200,250,300]});
  assert.deepEqual(numericTicks(-2,12,11,0),{min:-2,max:12,ticks:[-2,0,2,4,6,8,10,12]});
  assert.deepEqual(numericTicks(0,168,11,0,0,168).ticks,[0,20,40,60,80,100,120,140,160,168]);
});

test("zero, missing and fractional series keep finite nondegenerate axes",()=>{
  for(const bounds of [[Infinity,-Infinity],[0,0],[1,1]] as const){const scale=numericTicks(bounds[0],bounds[1],11,0);assert.ok(scale.max>scale.min);assert.ok(scale.ticks.every(Number.isFinite));}
  assert.deepEqual(numericTicks(0,.19,11).ticks,[0,.02,.04,.06,.08,.1,.12,.14,.16,.18,.2]);
});
