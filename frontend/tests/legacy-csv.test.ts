import assert from "node:assert/strict";
import test from "node:test";
import { legacyCsv } from "../lib/legacy-csv";

test("legacy CSV facade forwards byte chunks and the original query without buffering", async () => {
  const bytes = new TextEncoder().encode('канал,реакции\r\n"=formula",0\r\n');
  let pulls = 0;
  const stream = new ReadableStream<Uint8Array>({ pull(controller) {
    pulls++;
    if (pulls === 1) controller.enqueue(bytes.subarray(0, 7));
    else { controller.enqueue(bytes.subarray(7)); controller.close(); }
  } });
  const result = await legacyCsv(new Request("https://m.funpin.org/export/posts.csv?platform=vk&platform=tg&unused=1"), "posts", async (url, options) => {
    assert.equal(new URL(String(url)).pathname, "/api/v1/legacy-exports/posts.csv");
    assert.equal(new URL(String(url)).search, "?platform=vk&platform=tg&unused=1");
    assert.equal(options?.cache, "no-store");
    assert.equal(options?.redirect, "error");
    assert.ok(options?.signal);
    return new Response(stream, { headers: { "Content-Type": "text/csv; charset=utf-8", "Content-Disposition": 'attachment; filename="posts.csv"', "X-Dataset-Revision": "29", "Set-Cookie": "must-not-cross" } });
  });
  assert.equal(result.body, stream);
  assert.deepEqual(new Uint8Array(await result.arrayBuffer()), bytes);
  assert.equal(result.headers.get("Cache-Control"), "no-store");
  assert.equal(result.headers.get("Set-Cookie"), null);
  assert.equal(result.headers.get("X-Dataset-Revision"), "29");
});

test("classified compatibility failures stay failures and never become partial CSV", async () => {
  const result = await legacyCsv(new Request("https://m.funpin.org/export/snapshots.csv"), "snapshots", async () =>
    Response.json({ status: 409, code: "UNSAFE_RAW_JSON" }, { status: 409 }));
  assert.equal(result.status, 409);
  assert.equal((await result.json()).code, "UNSAFE_RAW_JSON");
  assert.equal(result.headers.get("Cache-Control"), "no-store");
});
