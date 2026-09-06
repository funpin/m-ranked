import test from "node:test";
import assert from "node:assert/strict";
import {redactVisualEvidence,visualCredentials} from "../scripts/visual-privacy.mjs";

test("visual evidence removes raw, HTML and RSC-escaped secret values",()=>{
  const token='csrf-value<&"\\token';
  const value=`<input name="csrf_token" value="${token.replaceAll("&","&amp;").replaceAll('"',"&quot;").replaceAll("<","&lt;")}"> ${JSON.stringify(token)} ${encodeURIComponent(token)} ${token}`;
  const result=redactVisualEvidence(value,[token]);
  for(const secret of [token,JSON.stringify(token).slice(1,-1),encodeURIComponent(token)])assert.equal(result.includes(secret),false);
  assert.equal((result.match(/REDACTED_SECRET/g)??[]).length,4);
  assert.match(result,/name="csrf_token"/);
});
test("authenticated visual configuration cannot silently use only half a credential pair",()=>{
  assert.equal(visualCredentials({},"TARGET"),null);
  assert.throws(()=>visualCredentials({LEGACY_ADMIN_USERNAME:"admin"},"LEGACY"),/must be supplied together/);
  assert.deepEqual(visualCredentials({TARGET_ADMIN_USERNAME:"admin",TARGET_ADMIN_PASSWORD:"test-only"},"TARGET"),{username:"admin",password:"test-only"});
});
