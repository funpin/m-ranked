import assert from "node:assert/strict";
import test from "node:test";
import { compareOverviewStatuses } from "../scripts/overview-semantics.mjs";

test("semantic gate rejects a one-card provider warning hidden below the screenshot pixel threshold",()=>{
  const expected=Array.from({length:207},(_,i)=>({title:`Вуз ${i}`,href:`/institutions/${i}`,text:"Нужен MAX_USER_PHONE",kind:"warn"}));
  const actual=expected.map((row)=>({...row}));
  actual[206]={...actual[206]!,text:"активен",kind:"ok"};
  assert.equal(compareOverviewStatuses(expected,actual).passed,false);
  assert.equal(compareOverviewStatuses(expected,actual).mismatches[0]?.index,206);
  assert.equal(compareOverviewStatuses(expected,expected.slice(0,50),true).passed,true);
  assert.equal(compareOverviewStatuses(expected,expected.slice(0,50)).passed,false);
  assert.equal(compareOverviewStatuses(expected,[] ,true).passed,false);
});
