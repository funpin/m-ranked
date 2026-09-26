import assert from "node:assert/strict";
import test from "node:test";
import { publicationCacheHeader, publicationCacheSeconds } from "../lib/cache-policy";

const now = Date.parse("2026-09-25T12:00:00Z");
const ago = (days: number) => new Date(now - days * 86_400_000).toISOString();

test("срок кэша страницы поста растёт с его возрастом", () => {
  assert.equal(publicationCacheSeconds(ago(0.5), now), 120);
  assert.equal(publicationCacheSeconds(ago(3), now), 900);
  assert.equal(publicationCacheSeconds(ago(20), now), 3600);
  assert.equal(publicationCacheSeconds(ago(41), now), 86_400);
  assert.equal(publicationCacheSeconds("мусор", now), 0);
  assert.equal(publicationCacheSeconds(ago(-1), now), 0);
});

test("срок ставится только когда история поста получена", async () => {
  const id = "4af36df4-271d-5408-8f47-512880569523";
  const url = new URL(`https://site.test/publications/${id}`);
  const requested: string[] = [];
  const ok = async (input: string | URL | Request) => {
    requested.push(String(input));
    return new Response(JSON.stringify({ publication: { publishedAt: "2020-01-01T00:00:00Z" } }), { status: 200 });
  };
  assert.equal(await publicationCacheHeader(url, "http://api.test", ok as typeof fetch), "86400");
  // Тот же запрос, что делает страница: ответ достаётся ей из кэша API.
  assert.equal(requested[0], `http://api.test/api/v1/publications/${id}/history?limit=3000`);
  const missing = async () => new Response("{}", { status: 404 });
  assert.equal(await publicationCacheHeader(url, "http://api.test", missing as typeof fetch), null);
  const down = async () => { throw new TypeError("fetch failed"); };
  assert.equal(await publicationCacheHeader(url, "http://api.test", down as typeof fetch), null);
  assert.equal(await publicationCacheHeader(new URL("https://site.test/accounts/" + id), "http://api.test", ok as typeof fetch), null);
});
