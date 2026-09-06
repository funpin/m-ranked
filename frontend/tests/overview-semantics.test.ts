import assert from "node:assert/strict";
import test from "node:test";
import { compareOverviewStatuses,canonicalOverviewStatuses } from "../scripts/overview-semantics.mjs";

test("overview semantics compare resolved legacy identities with canonical links without discarding hrefs",async()=>{
  const legacy=[{title:"Вуз",href:"/channels/7",text:"активен",kind:"ok"},
    {title:"Без аккаунта",href:null,text:"не добавлен",kind:"muted"}];
  const href="/accounts/00000001-0000-4000-8000-000000000007";
  const expected=await canonicalOverviewStatuses(legacy,async(value)=>{
    assert.equal(value,"/channels/7");return href;
  });
  assert.equal(legacy[0]!.href,"/channels/7");
  assert.equal(compareOverviewStatuses(expected,[{...legacy[0]!,href},legacy[1]!]).passed,true);
  assert.equal(compareOverviewStatuses(expected,[{...legacy[0]!,href:href.replace(/7$/,"8")},legacy[1]!]).passed,false);
  await assert.rejects(canonicalOverviewStatuses(legacy,async()=>{throw new Error("404");}),/404/);
});

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
