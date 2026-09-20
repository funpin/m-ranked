import assert from "node:assert/strict";
import test from "node:test";
import { createApiClient } from "../lib/api";
import { forgetAuthoritativeState, publicCacheKey, revisionCachedResponse, type PublicRepresentation, type PublicResponseCache } from "../lib/revision-cache";

function memory() {
  const entries = new Map<string, PublicRepresentation>();
  const cache: PublicResponseCache = { async load(key, _tags, produce) {
    const encoded = JSON.stringify(key);
    if (!entries.has(encoded)) entries.set(encoded, await produce());
    return entries.get(encoded)!;
  } };
  return { cache, entries };
}

test.beforeEach(() => forgetAuthoritativeState());

test("public cache keys include full canonical query, origin, domain and revision; private routes excluded", () => {
  const url = new URL("https://api.test/api/v1/compare?platform=vk&institutions=9&institutions=1&period=1d");
  assert.deepEqual(publicCacheKey(url, 7), publicCacheKey(new URL("https://api.test/api/v1/compare?period=1d&institutions=9&institutions=1&platform=vk"), 7));
  for (const changed of ["https://api.test/api/v1/compare?platform=max", "https://api.test/api/v1/statistics?platform=vk", "https://other.test/api/v1/compare?platform=vk"]) {
    assert.notDeepEqual(publicCacheKey(url, 7), publicCacheKey(new URL(changed), 7));
  }
  assert.notDeepEqual(publicCacheKey(url, 7), publicCacheKey(url, 8));
  for (const path of ["admin/jobs", "health/ready", "exports/publications.csv", "auth", "revision"]) assert.equal(publicCacheKey(new URL(`https://api.test/api/v1/${path}`), 7), null);
});

test("внутри окна свежести снимок читается один раз, а ответ отдаётся из кэша", async () => {
  const { cache } = memory();
  let revision = 1, reads = 0, fetches = 0;
  const url = new URL("https://api.test/api/v1/overview?platform=vk");
  const fetchResponse = async () => { fetches++; return Response.json({ datasetRevision: revision, items: [{ value: null }, { value: 0 }] }); };
  const readRevision = async () => { reads++; return revision; };

  const cold = await (await revisionCachedResponse(url, cache, fetchResponse, readRevision)).json();
  // Ревизия успела уехать вперёд — внутри окна это не повод ни перечитывать
  // её, ни считать ответ сбойным.
  revision = 9;
  assert.deepEqual(await (await revisionCachedResponse(url, cache, fetchResponse, readRevision)).json(), cold);
  assert.equal(fetches, 1, "второй читатель не ходит в API");
  assert.equal(reads, 1, "и не спрашивает ревизию заново");
});

test("новое окно свежести берёт новый снимок", async () => {
  const { cache, entries } = memory();
  let revision = 1;
  const url = new URL("https://api.test/api/v1/statistics");
  const fetchResponse = async () => Response.json({ datasetRevision: revision });
  await revisionCachedResponse(url, cache, fetchResponse, async () => revision);
  revision = 2;
  forgetAuthoritativeState();
  const fresh = await revisionCachedResponse(url, cache, fetchResponse, async () => revision);
  assert.equal((await fresh.json()).datasetRevision, 2);
  assert.equal(entries.size, 2, "у нового снимка свой ключ");
});

test("параллельные запросы страницы делят одно чтение снимка", async () => {
  const { cache } = memory();
  let reads = 0;
  const readRevision = async () => { reads++; return 5; };
  const fetchResponse = async (url: URL) => Response.json({ datasetRevision: 5, path: url.pathname });
  await Promise.all([
    revisionCachedResponse(new URL("https://api.test/api/v1/overview"), cache, fetchResponse, readRevision),
    revisionCachedResponse(new URL("https://api.test/api/v1/statistics"), cache, fetchResponse, readRevision),
    revisionCachedResponse(new URL("https://api.test/api/v1/compare"), cache, fetchResponse, readRevision),
  ]);
  assert.equal(reads, 1, "три запроса — одно чтение");
});

test("real generated transport asks for the authoritative revision once per window", async () => {
  const { cache } = memory(); const requests: string[] = [];
  const client = createApiClient({ baseUrl: "https://api.test", publicCache: cache, fetcher: async (input, init) => {
    const url = new URL(String(input)); requests.push(url.pathname);
    assert.equal(init?.cache, "no-store");
    return Response.json(url.pathname.endsWith("revision") ? { datasetRevision: 17, representationVersion: "a".repeat(64) } : { items: [], datasetRevision: 17, nextCursor: null, asOf: null });
  } });
  await client.overview({ platform: "vk", period: "1d" });
  await client.overview({ platform: "vk", period: "1d" });
  assert.deepEqual(requests, ["/api/v1/revision", "/api/v1/overview"]);
});

test("a representation deployment at unchanged PG revision cannot reuse an earlier DTO", async () => {
  const { cache, entries } = memory();let version="a".repeat(64);let fetches=0;
  const url=new URL("https://api.test/api/v1/overview");
  const fetchResponse=async () => {fetches++;return Response.json({datasetRevision:17,representation:version});};
  const readRevision=async () => ({datasetRevision:17,representationVersion:version});
  await revisionCachedResponse(url,cache,fetchResponse,readRevision);
  version="b".repeat(64);
  forgetAuthoritativeState();
  const fresh=await revisionCachedResponse(url,cache,fetchResponse,readRevision);
  assert.equal((await fresh.json()).representation,version);assert.equal(fetches,2);assert.equal(entries.size,2);
});

test("закреплённая ревизия идёт мимо кэша и мимо чтения снимка", async () => {
  // Страница детали собирается из нескольких запросов по одному снимку, и
  // закреплённый ответ намеренно приходит по прошлой ревизии.
  const { cache, entries } = memory();
  let fetches = 0, reads = 0;
  const url = new URL("https://api.test/api/v1/accounts/12?revision=41");
  const result = await revisionCachedResponse(url, cache,
    async () => { fetches++; return Response.json({ datasetRevision: 41 }); },
    async () => { reads++; return 44; });
  assert.equal((await result.json()).datasetRevision, 41);
  assert.equal(fetches, 1, "повторов быть не должно");
  assert.equal(reads, 0, "закреплённому запросу текущий снимок не нужен");
  assert.equal(entries.size, 0, "закреплённый ответ не кэшируется по текущей ревизии");
});

test("отказ API отдаётся как есть и не попадает в кэш", async () => {
  const { cache, entries } = memory();
  const result = await revisionCachedResponse(new URL("https://api.test/api/v1/overview"), cache,
    async () => Response.json({ detail: "boom" }, { status: 503 }),
    async () => 1);
  assert.equal(result.status, 503);
  assert.equal(entries.size, 0);
});
