import assert from "node:assert/strict";
import test from "node:test";
import { createBoundedPublicResponseCache } from "../lib/bounded-response-cache";

function response(body: string) {
  return { body, headers: [["content-type", "application/json"]] as [string, string][], status: 200 };
}

test("bounded public cache expires entries and coalesces concurrent production", async () => {
  let now = 1_000;
  let productions = 0;
  let release!: () => void;
  const gate = new Promise<void>((resolve) => { release = resolve; });
  const cache = createBoundedPublicResponseCache({ maxBytes: 1024, maxEntries: 4, ttlMs: 10, now: () => now });
  const produce = async () => { productions++; await gate; return response(`value-${productions}`); };

  const first = cache.load(["one"], [], produce);
  const concurrent = cache.load(["one"], [], produce);
  release();
  assert.equal((await first).body, "value-1");
  assert.equal((await concurrent).body, "value-1");
  assert.equal((await cache.load(["one"], [], produce)).body, "value-1");
  now += 10;
  assert.equal((await cache.load(["one"], [], async () => { productions++; return response(`value-${productions}`); })).body, "value-2");
});

test("bounded public cache evicts least-recently-used entries", async () => {
  let productions = 0;
  const cache = createBoundedPublicResponseCache({ maxBytes: 4096, maxEntries: 2, ttlMs: 1_000 });
  const load = (key: string) => cache.load([key], [], async () => response(`${key}-${++productions}`));
  await load("a"); await load("b"); await load("a"); await load("c");
  assert.equal((await load("a")).body, "a-1");
  assert.equal((await load("b")).body, "b-4");
});

test("bounded public cache does not retain a representation larger than its byte budget", async () => {
  let productions = 0;
  const cache = createBoundedPublicResponseCache({ maxBytes: 32, maxEntries: 4, ttlMs: 1_000 });
  const load = () => cache.load(["large"], [], async () => response(`body-${++productions}-is-larger-than-the-budget`));
  await load(); await load();
  assert.equal(productions, 2);
});

test("bounded public cache clears a failed in-flight producer", async () => {
  const cache = createBoundedPublicResponseCache({ maxBytes: 1024, maxEntries: 4, ttlMs: 1_000 });
  await assert.rejects(() => cache.load(["retry"], [], async () => { throw new Error("upstream failed"); }), /upstream failed/);
  assert.equal((await cache.load(["retry"], [], async () => response("recovered"))).body, "recovered");
});

test("bounded public cache rejects invalid limits", () => {
  assert.throws(() => createBoundedPublicResponseCache({ maxBytes: 0, maxEntries: 1, ttlMs: 1 }), /maxBytes/);
  assert.throws(() => createBoundedPublicResponseCache({ maxBytes: 1, maxEntries: 0, ttlMs: 1 }), /maxEntries/);
  assert.throws(() => createBoundedPublicResponseCache({ maxBytes: 1, maxEntries: 1, ttlMs: 0 }), /ttlMs/);
});
