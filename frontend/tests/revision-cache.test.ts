import assert from "node:assert/strict";
import test from "node:test";
import { createApiClient } from "../lib/api";
import { publicCacheKey, revisionCachedResponse, type PublicRepresentation, type PublicResponseCache } from "../lib/revision-cache";

function memory() {
  const entries = new Map<string, PublicRepresentation>();
  const cache: PublicResponseCache = { async load(key, _tags, produce) {
    const encoded = JSON.stringify(key);
    if (!entries.has(encoded)) entries.set(encoded, await produce());
    return entries.get(encoded)!;
  } };
  return { cache, entries };
}

test("public cache keys include full canonical query, origin, domain and revision; private routes excluded", () => {
  const url = new URL("https://api.test/api/v1/compare?platform=vk&institutions=9&institutions=1&period=1d");
  assert.deepEqual(publicCacheKey(url, 7), publicCacheKey(new URL("https://api.test/api/v1/compare?period=1d&institutions=9&institutions=1&platform=vk"), 7));
  for (const changed of ["https://api.test/api/v1/compare?platform=max", "https://api.test/api/v1/rating?platform=vk", "https://other.test/api/v1/compare?platform=vk"]) {
    assert.notDeepEqual(publicCacheKey(url, 7), publicCacheKey(new URL(changed), 7));
  }
  assert.notDeepEqual(publicCacheKey(url, 7), publicCacheKey(url, 8));
  for (const path of ["admin/jobs", "health/ready", "exports/publications.csv", "auth", "revision"]) assert.equal(publicCacheKey(new URL(`https://api.test/api/v1/${path}`), 7), null);
});

test("lost invalidation event cannot serve an earlier PG revision; cold, hot and disabled responses agree", async () => {
  const { cache } = memory();
  let revision = 1, reads = 0, fetches = 0;
  const url = new URL("https://api.test/api/v1/overview?platform=vk");
  const fetchResponse = async () => { fetches++; return Response.json({ datasetRevision: revision, items: [{ value: null }, { value: 0 }] }); };
  const readRevision = async () => { reads++; return revision; };
  const cold = await (await revisionCachedResponse(url, cache, fetchResponse, readRevision)).json();
  assert.deepEqual(await (await revisionCachedResponse(url, cache, fetchResponse, readRevision)).json(), cold);
  assert.equal(fetches, 1); assert.equal(reads, 2);
  revision = 2; // No event delivered and L1 still contains revision 1.
  const fresh = await (await revisionCachedResponse(url, cache, fetchResponse, readRevision)).json();
  assert.equal(fresh.datasetRevision, 2);
  assert.deepEqual(fresh, await (await fetchResponse()).json());
});

test("revision changes during fetch do not poison an earlier key", async () => {
  const { cache, entries } = memory();
  let revision = 1;
  const result = await revisionCachedResponse(new URL("https://api.test/api/v1/rating"), cache,
    async () => { revision = 2; return Response.json({ datasetRevision: revision }); }, async () => revision);
  assert.equal((await result.json()).datasetRevision, 2);
  assert.equal(entries.size, 1);
  assert.equal(JSON.parse([...entries.keys()][0]! ).at(-2), "2");
  assert.equal(JSON.parse([...entries.keys()][0]! ).at(-1), "unversioned");
});

test("real generated transport uses authoritative no-store revision with Next cache adapter", async () => {
  const { cache } = memory(); const requests: string[] = [];
  const client = createApiClient({ baseUrl: "https://api.test", publicCache: cache, fetcher: async (input, init) => {
    const url = new URL(String(input)); requests.push(url.pathname);
    assert.equal(init?.cache, "no-store");
    return Response.json(url.pathname.endsWith("revision") ? { datasetRevision: 17, representationVersion: "a".repeat(64) } : { items: [], datasetRevision: 17, nextCursor: null, asOf: null });
  } });
  await client.overview({ platform: "vk", period: "1d" });
  await client.overview({ platform: "vk", period: "1d" });
  assert.deepEqual(requests, ["/api/v1/revision", "/api/v1/overview", "/api/v1/revision"]);
});

test("a representation deployment at unchanged PG revision cannot reuse an earlier DTO", async () => {
  const { cache, entries } = memory();let version="a".repeat(64);let fetches=0;
  const url=new URL("https://api.test/api/v1/overview");
  const fetchResponse=async () => {fetches++;return Response.json({datasetRevision:17,representation:version});};
  const readRevision=async () => ({datasetRevision:17,representationVersion:version});
  await revisionCachedResponse(url,cache,fetchResponse,readRevision);
  version="b".repeat(64);
  const fresh=await revisionCachedResponse(url,cache,fetchResponse,readRevision);
  assert.equal((await fresh.json()).representation,version);assert.equal(fetches,2);assert.equal(entries.size,2);
});
